import zipfile
from datetime import datetime

import ifcopenshell.api

from utils.traversal import traverse, print_tree
from utils.mapper import classify
from utils.geometry import mesh_to_ifc, get_display_instances, _make_placement
from utils.instances import (
    is_instance, is_definition_source, instance_to_ifc, build_definition_map,
    print_instance_stats, get_definition_object,
)
from utils.properties import (
    get_building_storey, get_element_name, write_all_properties,
    PropertySetManager,
)
from utils.curves import curve_to_ifc
from utils.writer import create_ifc_scaffold, StoreyManager
from utils.type_manager import TypeManager
from utils.materials import MaterialManager


SPATIAL_STRUCTURE_TYPES = {
    "IfcBuilding", "IfcBuildingStorey",
    "IfcExternalSpatialElement", "IfcSpatialZone",
    "IfcGrid", "IfcAnnotation",
}

from pydantic import Field
from speckle_automate import (
    AutomateBase,
    AutomationContext,
    execute_automate_function,
)

class FunctionInputs(AutomateBase):
    """These are function author-defined values.

    Automate will make sure to supply them matching the types specified here.
    Please use the pydantic model schema to define your inputs:
    https://docs.pydantic.dev/latest/usage/models/
    """
    file_name: str = Field(
        title="File Name",
        description="The name of the IFC file.",
    )
    IFC_PROJECT_NAME : str = Field(
						title="IFC Project Name",
						description="The name of the IFC project.",
		)
    IFC_SITE_NAME : str = Field(
						title="IFC Site Name",
						description="The name of the IFC site.",
		)
    IFC_BUILDING_NAME : str = Field(
						title="IFC Building Name",
						description="The name of the IFC building.",
		)


def automate_function(
    automate_context: AutomationContext,
    function_inputs: FunctionInputs,
) -> None:
    print("=" * 60)
    print("  Speckle -> IFC4.3 Exporter")
    print("=" * 60)

    # ------------------------------------------------------------------ #
    # 1. Receive
    # ------------------------------------------------------------------ #
    base = automate_context.receive_version()

    # Uncomment to debug object tree:
    # print_tree(base)

    # ------------------------------------------------------------------ #
    # 2. Build definition map (for instance resolution)
    # ------------------------------------------------------------------ #
    definition_map = build_definition_map(base)

    # ------------------------------------------------------------------ #
    # 3. Set up IFC
    # ------------------------------------------------------------------ #
    ifc, _site, building, body_context = create_ifc_scaffold(
        project_name=function_inputs.IFC_PROJECT_NAME,
        site_name=function_inputs.IFC_SITE_NAME,
        building_name=function_inputs.IFC_BUILDING_NAME,
    )
    storey_manager = StoreyManager(ifc, building)
    material_manager = MaterialManager(ifc, base)
    material_manager.build_definition_material_map(definition_map)
    type_manager = TypeManager(ifc)
    property_manager = PropertySetManager(ifc)

    # ------------------------------------------------------------------ #
    # 4. Traverse & export
    # ------------------------------------------------------------------ #
    total           = 0
    no_geometry     = 0
    skipped_spatial = 0
    instance_count  = 0

    print(f"\nProcessing elements...\n")

    for obj in traverse(base):

        ifc_class = classify(obj)

        if ifc_class in SPATIAL_STRUCTURE_TYPES:
            skipped_spatial += 1
            continue

        # Skip objects that serve as instance definition geometry sources
        if is_definition_source(obj, definition_map):
            continue

        # Get building storey from properties
        storey_name = get_building_storey(obj)
        storey = storey_manager.get_or_create(storey_name)

        # Get element name
        name = get_element_name(obj)

        # ------------------------------------------------------------------ #
        # Path A: Instance object (has transform + definitionId)
        # ------------------------------------------------------------------ #
        if is_instance(obj):
            # Try to get a better IFC class from the definition object
            if ifc_class == "IfcBuildingElementProxy":
                def_obj = get_definition_object(obj, definition_map)
                if def_obj:
                    ifc_class = classify(def_obj)

            rep, placement = instance_to_ifc(
                ifc, body_context, obj, definition_map,
                scale=1.0, material_manager=material_manager,
            )
            if not rep:
                no_geometry += 1
                continue
            element = _create_element(ifc, ifc_class, name, rep, placement,
                                      storey, storey_manager=storey_manager)
            write_all_properties(ifc, element, obj, property_manager)
            type_manager.assign(element, obj, ifc_class)
            instance_count += 1
            total += 1

        else:
            # ------------------------------------------------------------------ #
            # Path B: Normal object — may have:
            #   B1. Direct mesh geometry in displayValue
            #   B2. Instance objects in displayValue
            #   B3. Curve geometry (Polycurve, Line, Arc)
            # ------------------------------------------------------------------ #

            # B1: Mesh geometry
            rep, placement = mesh_to_ifc(
                ifc, body_context, obj, scale=1.0,
                material_manager=material_manager,
            )
            if rep:
                element = _create_element(ifc, ifc_class, name, rep, placement,
                                          storey, storey_manager=storey_manager)
                write_all_properties(ifc, element, obj, property_manager)
                type_manager.assign(element, obj, ifc_class)
                total += 1

            # B2: Instance objects nested inside displayValue
            nested_instances = get_display_instances(obj)
            for inst in nested_instances:
                inst_rep, inst_placement = instance_to_ifc(
                    ifc, body_context, inst, definition_map,
                    scale=1.0, material_manager=material_manager,
                )
                if not inst_rep:
                    no_geometry += 1
                    continue
                inst_element = _create_element(
                    ifc, ifc_class, name, inst_rep, inst_placement,
                    storey, storey_manager=storey_manager,
                )
                write_all_properties(ifc, inst_element, obj, property_manager)
                type_manager.assign(inst_element, obj, ifc_class)
                instance_count += 1
                total += 1

            # B3: Curve geometry (Polycurve, Line, Arc) — fallback if no mesh/instances
            if not rep and not nested_instances:
                rep, placement = curve_to_ifc(
                    ifc, body_context, obj, scale=1.0,
                    material_manager=material_manager,
                )
                if rep:
                    element = _create_element(ifc, ifc_class, name, rep, placement,
                                              storey, storey_manager=storey_manager)
                    write_all_properties(ifc, element, obj, property_manager)
                    type_manager.assign(element, obj, ifc_class)
                    total += 1

            # Track if no path produced geometry
            if not rep and not nested_instances:
                no_geometry += 1

        if total % 100 == 0 and total > 0:
            print(f"  ... processed {total} elements")

    # ------------------------------------------------------------------ #
    # 5. Write output
    # ------------------------------------------------------------------ #
    print("\nFlushing spatial containment...")
    storey_manager.flush()
    print("Flushing type relationships...")
    type_manager.flush()
    print("Flushing shared property sets...")
    property_manager.flush()

    file_name = function_inputs.file_name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    ifc_filename = f"{file_name}_{timestamp}.ifc"

    ifc.write(ifc_filename)
    print(f"\nIFC file written: {ifc_filename}")

    zip_filename = f"{file_name}_{timestamp}.zip"
    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ifc_filename)
    print(f"Zipped: {zip_filename}")

    try:
        automate_context.mark_run_success("Success! You can download the IFC file below.")
        automate_context.store_file_result(f"./{zip_filename}")
    except Exception as e:
        print(f"  Could not upload file result (network issue?): {e}")
        automate_context.mark_run_failed(f"Something went wrong when storing file result. Exception detail: {e}") 

    print(f"\n{'=' * 60}")
    print(f"  Export complete!")
    print(f"  Total exported     : {total}")
    print(f"  Instances          : {instance_count}")
    print(f"  Without geometry   : {no_geometry}")
    print(f"  Skipped (spatial)  : {skipped_spatial}")
    print(f"  Storeys created    : {storey_manager.count}")
    print(f"  Levels             : {', '.join(storey_manager.names)}")
    print_instance_stats()
    material_manager.print_stats()
    property_manager.print_stats()
    print(f"{'=' * 60}\n")

def _create_element(ifc, ifc_class, name, rep, placement, storey,
                    storey_manager=None):
    """Helper: create an IFC element, assign geometry + placement, queue containment."""
    element = ifcopenshell.api.run("root.create_entity", ifc,
                                   ifc_class=ifc_class, name=str(name))

    if rep and placement:
        element.Representation = ifc.createIfcProductDefinitionShape(
            Representations=(rep,)
        )
        element.ObjectPlacement = placement
    elif placement:
        element.ObjectPlacement = placement
    else:
        element.ObjectPlacement = _make_placement(ifc, 0.0, 0.0, 0.0)

    # Queue spatial assignment (batched flush at end for performance)
    if storey_manager:
        if ifc_class in ("IfcSite", "IfcSpace"):
            storey_manager.queue_aggregate(storey, element)
        else:
            storey_manager.queue_contain(storey, element)
    return element

# make sure to call the function with the executor
if __name__ == "__main__":
    # NOTE: always pass in the automate function by its reference; do not invoke it!

    # Pass in the function reference with the inputs schema to the executor.
    execute_automate_function(automate_function, FunctionInputs)

    # If the function has no arguments, the executor can handle it like so
    # execute_automate_function(automate_function_without_inputs)