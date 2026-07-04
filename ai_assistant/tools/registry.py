"""Tool schemas exposed to the model, plus safety-gated dispatch to arcpy_tools."""
from ..providers.base import ToolDef
from . import arcpy_tools as impl

DESTRUCTIVE_TOOLS = {
    "create_feature_class",
    "add_features",
    "run_geoprocessing_tool",
    "import_reliability_form",
}


def build_tool_defs(allow_destructive):
    return [
        ToolDef(
            "list_layers",
            "List all layers in the active map, with type and source path.",
            {"type": "object", "properties": {}, "required": []},
        ),
        ToolDef(
            "describe_layer",
            "Get fields, geometry type, spatial reference, extent, and feature count for a layer.",
            {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Exact layer name as shown in the map's Contents pane.",
                    }
                },
                "required": ["layer_name"],
            },
        ),
        ToolDef(
            "query_features",
            "Run an attribute query (SQL WHERE clause) against a layer and return matching rows.",
            {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "where_clause": {
                        "type": "string",
                        "description": "SQL WHERE clause, e.g. \"OWNER = 'Smith'\". Use \"1=1\" to match all.",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Field names to return. Omit for all fields.",
                    },
                    "max_records": {"type": "integer", "default": 50},
                },
                "required": ["layer_name", "where_clause"],
            },
        ),
        ToolDef(
            "select_by_attribute",
            "Select features in a layer matching a WHERE clause (highlights them on the map).",
            {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "where_clause": {"type": "string"},
                    "selection_type": {
                        "type": "string",
                        "enum": [
                            "NEW_SELECTION",
                            "ADD_TO_SELECTION",
                            "REMOVE_FROM_SELECTION",
                            "SUBSET_SELECTION",
                            "CLEAR_SELECTION",
                        ],
                        "default": "NEW_SELECTION",
                    },
                },
                "required": ["layer_name", "where_clause"],
            },
        ),
        ToolDef(
            "buffer_layer",
            "Create a buffer polygon layer around the features of an existing layer and add it to the map.",
            {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "distance": {"type": "number"},
                    "distance_unit": {
                        "type": "string",
                        "enum": ["Feet", "Meters", "Miles", "Kilometers"],
                        "default": "Feet",
                    },
                    "out_name": {"type": "string", "description": "Name for the output feature class."},
                },
                "required": ["layer_name", "distance", "out_name"],
            },
        ),
        ToolDef(
            "create_feature_class",
            "Create a new, empty feature class in the project's default geodatabase and add it "
            "to the map. Destructive: creates new data.",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "geometry_type": {
                        "type": "string",
                        "enum": ["POINT", "MULTIPOINT", "POLYLINE", "POLYGON"],
                    },
                    "spatial_reference_wkid": {
                        "type": "integer",
                        "description": "e.g. 4326 for WGS84, 2229 for NAD83 California Zone V feet.",
                    },
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": ["TEXT", "SHORT", "LONG", "FLOAT", "DOUBLE", "DATE"],
                                },
                                "length": {"type": "integer"},
                            },
                            "required": ["name", "type"],
                        },
                        "description": "Attribute fields to add beyond the default OID/Shape fields.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually create the feature class.",
                        "default": False,
                    },
                },
                "required": ["name", "geometry_type", "spatial_reference_wkid", "confirm"],
            },
        ),
        ToolDef(
            "add_features",
            "Insert new feature rows (geometry + attributes) into an existing layer. "
            "Destructive: modifies data.",
            {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "features": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "geometry": {
                                    "type": "object",
                                    "description": "GeoJSON-style geometry, e.g. "
                                    '{"type": "Point", "coordinates": [x, y]}, in the '
                                    "layer's spatial reference units.",
                                },
                                "attributes": {
                                    "type": "object",
                                    "description": "Field name -> value pairs.",
                                },
                            },
                            "required": ["geometry"],
                        },
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["layer_name", "features", "confirm"],
            },
        ),
        ToolDef(
            "add_data_to_map",
            "Add an existing dataset (feature class, shapefile, raster, layer file) at a "
            "given path to the active map.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        ToolDef(
            "run_geoprocessing_tool",
            "Run any ArcPy geoprocessing tool by toolbox alias and tool name, e.g. "
            "toolbox_alias='management', tool_name='CopyFeatures'. This covers the full "
            "ArcGIS Pro geoprocessing catalog (Data Management, Analysis, Conversion, "
            "Cartography, Editing, and licensed extensions like Spatial Analyst or 3D "
            "Analyst) -- use it for anything not covered by the other tools. "
            "Destructive: can modify data or the project.",
            {
                "type": "object",
                "properties": {
                    "toolbox_alias": {
                        "type": "string",
                        "description": "arcpy toolbox alias, e.g. 'management', 'analysis', "
                        "'conversion', 'cartography', 'edit', 'sa' (Spatial Analyst), "
                        "'ddd' (3D Analyst) -- requires the matching extension license.",
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "Tool function name, e.g. 'CopyFeatures', 'Clip', 'Dissolve'.",
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Keyword arguments passed to the tool.",
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["toolbox_alias", "tool_name", "parameters", "confirm"],
            },
        ),
        ToolDef(
            "list_maps",
            "List every map in the project and which one is currently active.",
            {"type": "object", "properties": {}, "required": []},
        ),
        ToolDef(
            "add_map",
            "Create a new, empty map in the project from a template (does not affect existing maps).",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "template": {
                        "type": "string",
                        "description": "Map template name, e.g. 'Map' (2D) or 'Global Scene' (3D).",
                        "default": "Map",
                    },
                },
                "required": ["name"],
            },
        ),
        ToolDef(
            "set_active_map",
            "Open and switch to a different map in the project by name.",
            {
                "type": "object",
                "properties": {"map_name": {"type": "string"}},
                "required": ["map_name"],
            },
        ),
        ToolDef(
            "set_layer_visibility",
            "Show or hide a layer in the active map.",
            {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "visible": {"type": "boolean"},
                },
                "required": ["layer_name", "visible"],
            },
        ),
        ToolDef(
            "zoom_to_layer",
            "Zoom/pan the active map view to a layer's full extent.",
            {
                "type": "object",
                "properties": {"layer_name": {"type": "string"}},
                "required": ["layer_name"],
            },
        ),
        ToolDef(
            "list_bookmarks",
            "List the spatial bookmarks saved in the active map.",
            {"type": "object", "properties": {}, "required": []},
        ),
        ToolDef(
            "apply_bookmark",
            "Zoom the active map view to a saved bookmark by name.",
            {
                "type": "object",
                "properties": {"bookmark_name": {"type": "string"}},
                "required": ["bookmark_name"],
            },
        ),
        ToolDef(
            "list_layouts",
            "List every layout (print/export page) in the project.",
            {"type": "object", "properties": {}, "required": []},
        ),
        ToolDef(
            "export_map_to_file",
            "Export the current active map view to an image or PDF file.",
            {
                "type": "object",
                "properties": {
                    "out_path": {
                        "type": "string",
                        "description": "Full output file path, e.g. C:\\temp\\map.pdf. "
                        "Extension (.pdf/.png/.tif/.jpg) picks the format.",
                    },
                    "resolution": {"type": "integer", "default": 150, "description": "DPI for raster formats."},
                },
                "required": ["out_path"],
            },
        ),
        ToolDef(
            "export_layout_to_file",
            "Export a named layout to an image or PDF file.",
            {
                "type": "object",
                "properties": {
                    "layout_name": {"type": "string"},
                    "out_path": {"type": "string", "description": "Full output file path."},
                    "resolution": {"type": "integer", "default": 150, "description": "DPI for raster formats."},
                },
                "required": ["layout_name", "out_path"],
            },
        ),
        ToolDef(
            "save_project",
            "Save the current ArcGIS Pro project (.aprx) to disk.",
            {"type": "object", "properties": {}, "required": []},
        ),
        ToolDef(
            "import_reliability_form",
            "Bulk-import a 'Reliability Inspection Form V6.1' Excel file into the "
            "project's default geodatabase: creates/appends an 'Inspection_Jobs' table "
            "(one row per job -- Project ID, date, region, feeder, substation, "
            "inspector, device) and a 'Pole_Inspections' point feature class (one row "
            "per pole, related by Project ID). Only poles with GPS coordinates filled "
            "in are placed on the map; poles without coordinates are skipped and "
            "reported in the result. Destructive: creates/writes geodatabase data.",
            {
                "type": "object",
                "properties": {
                    "xlsx_path": {
                        "type": "string",
                        "description": "Full path to the .xlsx file, e.g. "
                        "C:\\Users\\name\\Downloads\\Reliability Inspection Form V6.1.xlsx",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "Worksheet name to read.",
                        "default": "Reliability Form",
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["xlsx_path", "confirm"],
            },
        ),
    ]


def dispatch(name, arguments, allow_destructive):
    """Returns (result_dict, is_error)."""
    fn = getattr(impl, name, None)
    if fn is None:
        return {"error": f"Unknown tool '{name}'."}, True

    if name in DESTRUCTIVE_TOOLS:
        if not allow_destructive:
            return (
                {
                    "error": "Destructive actions are disabled for this run (the "
                    "'Allow destructive actions' parameter is unchecked). No changes "
                    "were made. Tell the user they need to re-run with that box checked."
                },
                True,
            )
        if not arguments.get("confirm"):
            return (
                {
                    "error": "confirm=true was not set; no changes were made. Ask the "
                    "user to confirm before proceeding, or pass confirm=true if you "
                    "already have clear instructions to proceed."
                },
                True,
            )

    call_args = {k: v for k, v in arguments.items() if k != "confirm"}
    try:
        return fn(**call_args), False
    except Exception as exc:  # noqa: BLE001 - surface all arcpy errors back to the model
        return {"error": f"{type(exc).__name__}: {exc}"}, True
