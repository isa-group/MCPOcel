"""Provider adapters for OpenAI and Gemini with native tool calling support."""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Add parent directory to path for importing from server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google.genai as genai
from google.genai import types as genai_types
from openai import OpenAI


class ProviderError(RuntimeError):
    pass

@dataclass
class ToolCall:
    """Represents a tool call requested by the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass
class ChatResponse:
    """Response from an LLM chat completion."""
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None


class BaseProvider:
    """Base class for LLM providers with native tool calling support."""
    
    def _convert_mcp_tools(self, mcp_tools: List[Dict[str, Any]]) -> Any:
        """Convert MCP tool definitions to provider-specific format."""
        raise NotImplementedError

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], model: str, tools: List[Dict[str, Any]]
    ) -> ChatResponse:
        """Execute a chat completion with tool calling support."""
        raise NotImplementedError

    def build_assistant_tool_call_message(
        self, content: str, tool_calls: List[ToolCall]
    ) -> Dict[str, Any]:
        """Build an assistant message containing tool calls."""
        raise NotImplementedError

    def build_tool_result_message(
        self, tool_call: ToolCall, result: str
    ) -> Dict[str, Any]:
        """Build a message containing a tool result."""
        raise NotImplementedError

    def build_user_turn(
        self, user_text: str, append_instruction: str = ""
    ) -> List[Dict[str, Any]]:
        """Build the messages to add for a user turn, injecting the reminder
        instruction in the most effective way for this provider."""
        raise NotImplementedError


class OpenAIProvider(BaseProvider):
    """OpenAI API provider using the /v1/responses endpoint.

    All current OpenAI models (GPT-4o, o3, o4-mini, deep-research variants,
    etc.) support this endpoint, which is the new unified API surface.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is required for provider 'openai'")
        self.client = OpenAI(api_key=api_key)

    def _convert_mcp_tools(self, mcp_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert MCP tool definitions to the Responses API function tool format."""
        result = []
        for tool in mcp_tools:
            input_schema = tool.get("inputSchema", {})
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])

            flat_properties: Dict[str, Any] = {}
            for prop_name, prop_info in properties.items():
                if isinstance(prop_info, dict):
                    flat_properties[prop_name] = {
                        "type": prop_info.get("type", "string"),
                        "description": prop_info.get("description", ""),
                    }
                else:
                    flat_properties[prop_name] = {"type": "string"}

            result.append({
                "type": "function",
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": flat_properties,
                    "required": required,
                },
            })
        return result

    def _build_input(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert message history to the Responses API input format.

        Mapping:
          - system      → developer role (required by o-series reasoning models)
          - user        → user role (unchanged)
          - assistant   → assistant role
          - _type=="responses_function_calls" → expanded function_call items
          - type=="function_call_output"      → kept as-is
        """
        items: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.get("_type") == "responses_function_calls":
                # If the model produced text before the tool calls, prepend it.
                if msg.get("content"):
                    items.append({"role": "assistant", "content": msg["content"]})
                items.extend(msg["calls"])
            elif msg.get("type") == "function_call_output":
                items.append(msg)
            else:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    items.append({"role": "developer", "content": content})
                elif role in ("user", "assistant"):
                    items.append({"role": role, "content": content})
                # Ignore Gemini-specific or unknown keys
        return items

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], model: str, tools: List[Dict[str, Any]]
    ) -> ChatResponse:
        """Execute a request via /v1/responses."""
        input_items = self._build_input(messages)
        openai_tools = self._convert_mcp_tools(tools)

        kwargs: Dict[str, Any] = {"model": model, "input": input_items}
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = self.client.responses.create(**kwargs)

        content = ""
        parsed_tool_calls: List[ToolCall] = []

        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    if hasattr(part, "text"):
                        content += part.text
            elif item.type == "function_call":
                try:
                    arguments = json.loads(item.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                parsed_tool_calls.append(ToolCall(
                    id=item.call_id,
                    name=item.name,
                    arguments=arguments,
                ))

        return ChatResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            finish_reason=None,
        )

    def build_assistant_tool_call_message(
        self, content: str, tool_calls: List[ToolCall]
    ) -> Dict[str, Any]:
        """Build an assistant turn with function calls for the Responses API."""
        return {
            "_type": "responses_function_calls",
            "content": content,
            "calls": [
                {
                    "type": "function_call",
                    "call_id": tc.id,
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                }
                for tc in tool_calls
            ],
        }

    def build_tool_result_message(
        self, tool_call: ToolCall, result: str
    ) -> Dict[str, Any]:
        """Build a function_call_output item for the Responses API."""
        return {
            "type": "function_call_output",
            "call_id": tool_call.id,
            "output": result,
        }

    def build_user_turn(
        self, user_text: str, append_instruction: str = ""
    ) -> List[Dict[str, Any]]:
        """Inject the instruction as a separate system (→ developer) message
        for maximum priority, followed by the user message."""
        return [
            {"role": "user", "content": user_text.strip()},
            {"role": "developer", "content": append_instruction.strip()},
        ]


class GeminiProvider(BaseProvider):
    """Google Gemini API provider with native tool calling support."""
    
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is required for provider 'gemini'")
        self.client = genai.Client(api_key=api_key)
        # Stores the raw Content from the last model response so that thought
        # parts (and their thought_signature) are preserved when the conversation
        # is sent back to Gemini after tool execution.
        self._last_raw_content: Optional[genai_types.Content] = None

    def _convert_mcp_tools(self, mcp_tools: List[Dict[str, Any]]) -> List[genai_types.FunctionDeclaration]:
        """Convert MCP tool definitions to Gemini FunctionDeclaration format."""
        declarations = []
        for tool in mcp_tools:
            input_schema = tool.get("inputSchema", {})
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])
            
            gemini_properties: Dict[str, Any] = {}
            for prop_name, prop_info in properties.items():
                if isinstance(prop_info, dict):
                    prop_type = prop_info.get("type", "string").upper()
                    type_mapping = {
                        "STRING": "STRING",
                        "INTEGER": "INTEGER",
                        "NUMBER": "NUMBER",
                        "BOOLEAN": "BOOLEAN",
                        "ARRAY": "ARRAY",
                        "OBJECT": "OBJECT",
                    }
                    gemini_properties[prop_name] = {
                        "type": type_mapping.get(prop_type, "STRING"),
                        "description": prop_info.get("description", ""),
                    }
            
            declarations.append(genai_types.FunctionDeclaration(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters={
                    "type": "OBJECT",
                    "properties": gemini_properties,
                    "required": required,
                } if gemini_properties else None,
            ))
        
        return declarations

    def _convert_messages_to_contents(
        self, messages: List[Dict[str, Any]]
    ) -> List[genai_types.Content]:
        """Convert provider-agnostic messages to Gemini Content format."""
        contents: List[genai_types.Content] = []
        
        for msg in messages:
            role = msg.get("role", "user")
            
            if role == "system":
                continue
            
            # For assistant messages that contain tool calls we stored the
            # original Content object from the model response.  Re-use it
            # verbatim so that thought parts and their thought_signature are
            # preserved – Gemini requires them to be present when tool results
            # are returned.
            if role == "assistant" and msg.get("gemini_raw_content") is not None:
                contents.append(msg["gemini_raw_content"])
                continue
            
            gemini_role = "model" if role == "assistant" else "user"
            parts: List[genai_types.Part] = []
            
            if msg.get("content"):
                parts.append(genai_types.Part(text=msg["content"]))
            
            if role == "assistant" and msg.get("gemini_function_calls"):
                for fc in msg["gemini_function_calls"]:
                    parts.append(genai_types.Part(
                        function_call=genai_types.FunctionCall(
                            name=fc["name"],
                            args=fc["args"],
                        )
                    ))
            
            if role == "tool_result":
                gemini_role = "user"
                parts = [genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=msg["name"],
                        response={"result": msg["content"]},
                    )
                )]
            
            if parts:
                contents.append(genai_types.Content(role=gemini_role, parts=parts))
        
        return contents

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], model: str, tools: List[Dict[str, Any]]
    ) -> ChatResponse:
        """Execute a chat completion with native Gemini tool calling."""
        gemini_declarations = self._convert_mcp_tools(tools)
        gemini_tools = [genai_types.Tool(function_declarations=gemini_declarations)]
        
        system_instruction = None
        for msg in messages:
            if msg.get("role") == "system":
                system_instruction = msg.get("content", "")
                break
        
        contents = self._convert_messages_to_contents(messages)
        model_name = f"models/{model}" if not model.startswith("models/") else model
        
        response = self.client.models.generate_content(
            model=model_name,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                tools=gemini_tools,
                system_instruction=system_instruction,
            ),
        )
        
        content = ""
        parsed_tool_calls: List[ToolCall] = []
        self._last_raw_content = None
        
        if response.candidates and response.candidates[0].content:
            raw_content = response.candidates[0].content
            self._last_raw_content = raw_content
            for part in raw_content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    parsed_tool_calls.append(ToolCall(
                        id=f"gemini_{uuid.uuid4().hex[:8]}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))
                elif hasattr(part, "text") and part.text and not getattr(part, "thought", False):
                    content += part.text
        
        finish_reason = None
        if response.candidates:
            finish_reason = str(response.candidates[0].finish_reason)
        
        return ChatResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            finish_reason=finish_reason,
        )

    def build_assistant_tool_call_message(
        self, content: str, tool_calls: List[ToolCall]
    ) -> Dict[str, Any]:
        """Build a Gemini assistant message with tool calls.
        
        When available, the raw Content object from the last model response is
        embedded under ``gemini_raw_content`` so that thought parts and their
        ``thought_signature`` survive round-trips through the message history.
        """
        msg: Dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "gemini_function_calls": [
                {"name": tc.name, "args": tc.arguments}
                for tc in tool_calls
            ],
        }
        if self._last_raw_content is not None:
            msg["gemini_raw_content"] = self._last_raw_content
            self._last_raw_content = None  # consume – avoid stale references
        return msg

    def build_tool_result_message(
        self, tool_call: ToolCall, result: str
    ) -> Dict[str, Any]:
        """Build a Gemini tool result message."""
        return {
            "role": "tool_result",
            "name": tool_call.name,
            "content": result,
        }

    def build_user_turn(
        self, user_text: str, append_instruction: str = ""
    ) -> List[Dict[str, Any]]:
        """Embed the instruction in the user content (Gemini only supports
        user/model/tool_result roles, not system mid-conversation)."""
        return [{"role": "user", "content": f"{user_text}\n\n{append_instruction}".strip()}]


def build_provider(name: str) -> BaseProvider:
    normalized = name.lower()
    if normalized == "openai":
        return OpenAIProvider(api_key=os.getenv("OPENAI_API_KEY", ""))
    if normalized == "gemini":
        return GeminiProvider(api_key=os.getenv("GEMINI_API_KEY", ""))
    raise ProviderError(f"Unknown provider: {name}")
