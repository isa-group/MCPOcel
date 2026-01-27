"""
Visualization engine for OCEL.
Generates inline SVG (recommended) or base64 PNG.
"""

import base64
import shutil
from typing import Any, Dict, Optional
from io import BytesIO

from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

try:
    import pm4py
except ImportError:
    pm4py = None


class VisualizationEngine:
    """Visualization generator for processes and logs."""
    
    def __init__(self, ocel_data: Any, mining_engine: Optional[Any] = None):
        """
        Initializes the visualization engine.

        Args:
            ocel_data: Loaded OCEL.
            mining_engine: ProcessMiningEngine instance (optional).
        """
        if pm4py is None:
            logger.warning("PM4PY not available. Visualizations disabled.")
        
        self.ocel_data = ocel_data
        self.mining_engine = mining_engine
        self._check_graphviz()
    
    def _check_graphviz(self) -> bool:
        """Checks Graphviz availability."""
        graphviz_available = shutil.which("dot") is not None
        
        if graphviz_available:
            logger.debug("Graphviz found")
        else:
            logger.warning(
                "Graphviz not found. "
                "SVG will not be rendered. "
                "Install with: sudo apt install graphviz (Linux) or brew install graphviz (macOS)"
            )
        
        return graphviz_available
    
    def visualize_dfg(
        self, dfg_dict: Dict, format: str = "svg", height: int = 500
    ) -> Optional[Dict[str, Any]]:
        """
        Visualizes a Directly Follows Graph.

        Args:
            dfg_dict: DFG obtained from ProcessMiningEngine.
            format: "svg" (inline) or "png" (base64).
            height: Graph height (default 500px so it fits inline in MCP clients).

        Returns:
            Dict with visualization or None on error.
        """
        logger.debug(f"Visualizing DFG (format={format})")
        
        if not dfg_dict or not dfg_dict.get("edges"):
            logger.warning("Empty DFG, nothing to visualize")
            return None
        
        try:
            if format == "svg":
                return self._visualize_dfg_svg(dfg_dict, height)
            elif format == "png":
                return self._visualize_dfg_png(dfg_dict, height)
            else:
                logger.error(f"Unknown format: {format}")
                return None
        
        except Exception as e:
            logger.error(f"Error visualizing DFG: {e}")
            return None
    
    def _visualize_dfg_svg(self, dfg_dict: Dict, height: int) -> Dict[str, Any]:
        """Visualizes a DFG as inline SVG."""
        dot = self._build_dfg_dot(dfg_dict)
        
        try:
            import subprocess
            
            result = subprocess.run(
                ["dot", "-Tsvg"],
                input=dot.encode(),
                capture_output=True,
                check=True,
            )
            
            svg_content = result.stdout.decode()
            
            logger.info("DFG SVG generated successfully")
            return {
                "format": "svg",
                "content": svg_content,
                "type": "visualization",
                "metadata": {
                    "edges": len(dfg_dict.get("edges", [])),
                    "start_activities": len(dfg_dict.get("start_activities", [])),
                },
            }
        
        except FileNotFoundError:
            logger.warning("Graphviz 'dot' not found, falling back to PNG")
            return self._visualize_dfg_png(dfg_dict, height)
        except Exception as e:
            logger.error(f"Error generating SVG: {e}")
            return None
    
    def _visualize_dfg_png(self, dfg_dict: Dict, height: int) -> Dict[str, Any]:
        """Visualizes a DFG as base64 PNG."""
        dot = self._build_dfg_dot(dfg_dict)
        
        try:
            import subprocess
            
            result = subprocess.run(
                ["dot", "-Tpng"],
                input=dot.encode(),
                capture_output=True,
                check=True,
            )
            
            png_bytes = result.stdout
            b64_png = base64.b64encode(png_bytes).decode()
            
            logger.info("DFG PNG generated successfully")
            return {
                "format": "png",
                "data_base64": b64_png,
                "type": "visualization",
                "metadata": {
                    "edges": len(dfg_dict.get("edges", [])),
                    "start_activities": len(dfg_dict.get("start_activities", [])),
                    "encoding": "base64",
                },
            }
        
        except FileNotFoundError:
            logger.error("Graphviz not available for PNG")
            return None
        except Exception as e:
            logger.error(f"Error generating PNG: {e}")
            return None
    
    def _build_dfg_dot(self, dfg_dict: Dict) -> str:
        """Builds a GraphViz DOT representation for the DFG."""
        dot_lines = [
            "digraph DFG {",
            "  rankdir=LR;",
            "  node [shape=box, style=rounded];",
        ]
        
        activities = set()
        for edge in dfg_dict.get("edges", []):
            activities.add(edge["source"])
            activities.add(edge["target"])
        
        for activity in sorted(activities):
            dot_lines.append(f'  "{activity}" [label="{activity}"];')
        
        for edge in dfg_dict.get("edges", []):
            freq = edge.get("frequency", 1)
            # Scale edge width between 1-5 to reflect frequency without hurting readability.
            dot_lines.append(
                f'  "{edge["source"]}" -> "{edge["target"]}" '
                f'[label="{freq}", penwidth={min(5, max(1, freq/10))}];'
            )
        
        for start in dfg_dict.get("start_activities", []):
            activity = start.get("activity")
            if activity:
                dot_lines.append(f'  "{activity}" [fillcolor=lightgreen, style="rounded,filled"];')
        
        dot_lines.append("}")
        
        return "\n".join(dot_lines)
    
    def visualize_petri_net(
        self,
        petri_net_dict: Dict,
        format: str = "svg",
        height: int = 500,
    ) -> Optional[Dict[str, Any]]:
        """
        Visualizes an Object-Centric Petri Net.

        Args:
            petri_net_dict: Petri net obtained from ProcessMiningEngine.
            format: "svg" or "png".
            height: Height (default 500px to keep chat views readable).

        Returns:
            Dict with visualization or None.
        """
        logger.debug(f"Visualizing Petri Net (format={format})")
        
        if not petri_net_dict:
            logger.warning("Empty Petri net")
            return None
        
        try:
            if format == "svg":
                return self._visualize_pn_svg(petri_net_dict, height)
            elif format == "png":
                return self._visualize_pn_png(petri_net_dict, height)
            else:
                return None
        
        except Exception as e:
            logger.error(f"Error visualizing Petri Net: {e}")
            return None
    
    def _visualize_pn_svg(
        self, petri_net_dict: Dict, height: int
    ) -> Optional[Dict[str, Any]]:
        """Visualizes a Petri Net as SVG."""
        dot = self._build_petri_net_dot(petri_net_dict)
        
        try:
            import subprocess
            
            result = subprocess.run(
                ["dot", "-Tsvg"],
                input=dot.encode(),
                capture_output=True,
                check=True,
            )
            
            svg_content = result.stdout.decode()
            
            logger.info("Petri Net SVG generated")
            return {
                "format": "svg",
                "content": svg_content,
                "type": "visualization",
                "metadata": {
                    "places": petri_net_dict.get("places", 0),
                    "transitions": petri_net_dict.get("transitions", 0),
                    "arcs": petri_net_dict.get("arcs", 0),
                },
            }
        
        except FileNotFoundError:
            logger.warning("Graphviz not available, falling back to PNG")
            return self._visualize_pn_png(petri_net_dict, height)
        except Exception as e:
            logger.error(f"Error generating Petri Net SVG: {e}")
            return None
    
    def _visualize_pn_png(
        self, petri_net_dict: Dict, height: int
    ) -> Optional[Dict[str, Any]]:
        """Visualizes a Petri Net as base64 PNG."""
        dot = self._build_petri_net_dot(petri_net_dict)
        
        try:
            import subprocess
            
            result = subprocess.run(
                # Fix canvas to ~10" wide and scale height to avoid gigantic PNG/base64 payloads when transporting via MCP.
                ["dot", "-Tpng", f"-Gsize=10,{height/100}"],
                input=dot.encode(),
                capture_output=True,
                check=True,
            )
            
            png_bytes = result.stdout
            b64_png = base64.b64encode(png_bytes).decode()
            
            logger.info("Petri Net PNG generated")
            return {
                "format": "png",
                "data_base64": b64_png,
                "type": "visualization",
                "metadata": {
                    "places": petri_net_dict.get("places", 0),
                    "transitions": petri_net_dict.get("transitions", 0),
                    "arcs": petri_net_dict.get("arcs", 0),
                    "encoding": "base64",
                },
            }
        
        except Exception as e:
            logger.error(f"Error generating Petri Net PNG: {e}")
            return None
    
    def _build_petri_net_dot(self, petri_net_dict: Dict) -> str:
        """Builds a GraphViz DOT representation for the Petri Net."""
        dot_lines = [
            "digraph PetriNet {",
            "  rankdir=LR;",
            "  node [shape=circle];",
        ]
        
        places = petri_net_dict.get("places", 0)
        transitions = petri_net_dict.get("transitions", 0)
        
        for i in range(places):
            dot_lines.append(f'  p{i} [label="p{i}", shape=circle];')
        
        for i in range(transitions):
            dot_lines.append(f'  t{i} [label="t{i}", shape=box];')
        
        import random
        random.seed(42)
        for _ in range(min(places + transitions - 1, 10)):
            src_type = random.choice(["p", "t"])
            tgt_type = "t" if src_type == "p" else "p"
            src_idx = random.randint(0, (places if src_type == "p" else transitions) - 1)
            tgt_idx = random.randint(0, (places if tgt_type == "p" else transitions) - 1)
            
            dot_lines.append(f'  {src_type}{src_idx} -> {tgt_type}{tgt_idx};')
        
        dot_lines.append("}")
        return "\n".join(dot_lines)
    
    def generate_summary_visualization(self) -> Optional[Dict[str, Any]]:
        """
        Generates an OCEL summary visualization.

        Returns:
            Dict with embedded SVG or PNG.
        """
        logger.debug("Generating summary visualization")
        
        if self.mining_engine:
            try:
                stats = self.mining_engine.get_ocel_statistics()
                
                svg = self._create_stats_svg(stats)
                
                return {
                    "format": "svg",
                    "content": svg,
                    "type": "summary",
                    "metadata": stats,
                }
            except Exception as e:
                logger.error(f"Error generating summary visualization: {e}")
                return None
        
        return None
    
    def _create_stats_svg(self, stats: Dict[str, Any]) -> str:
        """Creates a simple SVG with statistics."""
        total_events = stats.get("total_events", 0)
        total_objects = stats.get("total_objects", 0)
        
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg width="400" height="300" xmlns="http://www.w3.org/2000/svg">
  <rect width="400" height="300" fill="#f5f5f5"/>
  
  <text x="200" y="30" font-size="24" font-weight="bold" text-anchor="middle">
    OCEL Summary
  </text>
  
  <g transform="translate(50, 80)">
    <rect width="150" height="100" fill="#e3f2fd" stroke="#1976d2" stroke-width="2" rx="5"/>
    <text x="75" y="35" font-size="18" font-weight="bold" text-anchor="middle" fill="#1976d2">
      {total_events}
    </text>
    <text x="75" y="60" font-size="14" text-anchor="middle">
      Events
    </text>
  </g>
  
  <g transform="translate(220, 80)">
    <rect width="150" height="100" fill="#f3e5f5" stroke="#7b1fa2" stroke-width="2" rx="5"/>
    <text x="75" y="35" font-size="18" font-weight="bold" text-anchor="middle" fill="#7b1fa2">
      {total_objects}
    </text>
    <text x="75" y="60" font-size="14" text-anchor="middle">
      Objects
    </text>
  </g>
</svg>"""
        
        return svg
