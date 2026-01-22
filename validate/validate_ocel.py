import json
import os
import requests
from jsonschema import validate, ValidationError

# URL oficial del esquema OCEL 2.0 JSON
SCHEMA_URL = "https://raw.githubusercontent.com/ocel-standard/ocel-standard/main/schemas/ocel_2_0.json"

def validate_ocel(ocel_path, schema_path="schemas/ocel_2_0.json"):
    print("\n Validating...")

# Official Schema Download
    if not os.path.exists(schema_path) or os.path.getsize(schema_path) == 0:
        os.makedirs(os.path.dirname(schema_path), exist_ok=True)
        print("Downloading official OCEL 2.0 Schema...")
        try:
            resp = requests.get(SCHEMA_URL)
            resp.raise_for_status()

            schema_data = resp.json()

            with open(schema_path, "w") as f:
                json.dump(schema_data, f, indent=2)
            print("Schema downloaded successfully.")
        except Exception as e:
            print(f"Error downloading schema: {e}")
            return False

    # Validate Syntax
    with open(ocel_path) as f:
        ocel = json.load(f)
    with open(schema_path) as f:
        schema = json.load(f)

    try:
        validate(instance=ocel, schema=schema)
        print("Syntax validation successful")
    except ValidationError as e:
        print(f"Syntax errors : {e.message}")
        return False

    # Validate Semantics
    defined_objs = set(ocel["ocel:objects"].keys())
    errors = []
    for eid, event in ocel["ocel:events"].items():
        for obj_id in event["ocel:omap"]:
            if obj_id not in defined_objs:
                errors.append(f"Event {eid} reference object does not exist {obj_id}")

    if errors:
        print(f"Semantic errors  ({len(errors)}):")
        print(errors[0])  # Mostramos el primero
        return False
    else:
        print("Complete validation successful.")
        return True