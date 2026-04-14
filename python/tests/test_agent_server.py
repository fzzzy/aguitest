import pytest
import base64
from agent_server import parse_data_url, evaluate_expression, dangerous_tool, process_text_attachment, process_binary_attachment, tool_schema_to_a2ui

def test_parse_data_url_valid():
    result = parse_data_url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB")
    assert result is not None
    media_type, b64 = result
    assert media_type == "image/png"
    assert b64 == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"

def test_parse_data_url_invalid():
    assert parse_data_url("not a valid url") is None
    assert parse_data_url("data:image/png;base64") is None

def test_evaluate_expression():
    assert evaluate_expression("2 + 2") == "4"
    assert evaluate_expression("10 ** 2") == "100"
    
def test_evaluate_expression_error():
    result = evaluate_expression("1 / 0")
    assert "inf" in result

def test_dangerous_tool():
    result = dangerous_tool("testing")
    assert result == "grfgvat"

def test_process_text_attachment():
    data = "Hello, AGUI!"
    b64_data = base64.b64encode(data.encode("utf-8")).decode("utf-8")
    
    result = process_text_attachment(b64_data, "hello.txt")
    
    assert 'name="hello.txt"' in result.text
    assert "Hello, AGUI!" in result.text
    assert "<file-attachment" in result.text

def test_process_binary_attachment():
    data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
    result = process_binary_attachment("image/png", data, "pixel.png")
    
    assert result.mime_type == "image/png"
    assert result.data == data
    assert result.filename == "pixel.png"

class MockSchema:
    def __init__(self, json_schema):
        self.json_schema = json_schema

class MockTool:
    def __init__(self, json_schema):
        self.function_schema = MockSchema(json_schema)

def test_tool_schema_to_a2ui_empty():
    tool = MockTool({})
    result = tool_schema_to_a2ui("empty_tool", tool)
    
    # Expect surfaceUpdate and beginRendering messages
    assert len(result) == 2
    surface_update = result[0]["surfaceUpdate"]
    assert surface_update["surfaceId"] == "empty_tool"
    assert len(surface_update["components"]) == 2 # Column container and Submit button

def test_tool_schema_to_a2ui_with_properties():
    schema = {
        "properties": {
            "name": {
                "title": "Name",
                "description": "The user name",
                "type": "string"
            },
            "age": {
                "title": "Age",
                "type": "integer"
            }
        },
        "required": ["name"]
    }
    tool = MockTool(schema)
    result = tool_schema_to_a2ui("user_form", tool)
    
    # Expect surfaceUpdate and beginRendering messages
    assert len(result) == 2
    surface_update = result[0]["surfaceUpdate"]
    
    # 4 components: form, name input, age input, submit button
    components = surface_update["components"]
    assert len(components) == 4
    
    name_field = next(c for c in components if c["id"] == "user_form-name")
    assert name_field["component"]["TextField"]["label"] == {"literalString": "name"}
    
    age_field = next(c for c in components if c["id"] == "user_form-age")
    assert age_field["component"]["TextField"]["label"] == {"literalString": "age"}
    
    begin_rendering = result[1]["beginRendering"]
    assert begin_rendering["root"] == "user_form-form"
    assert begin_rendering["surfaceId"] == "user_form"

def test_tool_schema_to_a2ui_boolean():
    schema = {
        "properties": {
            "active": {
                "type": "boolean"
            }
        }
    }
    tool = MockTool(schema)
    result = tool_schema_to_a2ui("boolean_tool", tool)
    
    surface_update = result[0]["surfaceUpdate"]
    components = surface_update["components"]
    
    active_field = next(c for c in components if c["id"] == "boolean_tool-active")
    assert "Checkbox" in active_field["component"]
    assert active_field["component"]["Checkbox"]["label"] == {"literalString": "active"}
    assert active_field["component"]["Checkbox"]["dataModelKey"] == "active"

