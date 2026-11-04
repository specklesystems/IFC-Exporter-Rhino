"""Speckle Automate function: export the triggering model version to IFC4X3."""

import zipfile
from datetime import datetime
from pathlib import Path

from pydantic import Field
from speckle_automate import (
    AutomateBase,
    AutomationContext,
    execute_automate_function,
)
from specklepy.logging.exceptions import SpeckleException

from utils.exporter import export_model


class FunctionInputs(AutomateBase):
    """Names written into the exported IFC file."""

    file_name: str = Field(
        title="File Name",
        description="The name of the IFC file (a timestamp is appended).",
    )
    IFC_PROJECT_NAME: str = Field(
        title="IFC Project Name",
        description="The name of the IFC project.",
    )
    IFC_SITE_NAME: str = Field(
        title="IFC Site Name",
        description="The name of the IFC site.",
    )
    IFC_BUILDING_NAME: str = Field(
        title="IFC Building Name",
        description="The name of the IFC building.",
    )


def automate_function(
    automate_context: AutomationContext,
    function_inputs: FunctionInputs,
) -> None:
    print("=" * 60)
    print("  Speckle -> IFC4X3 Exporter")
    print("=" * 60)

    try:
        model = automate_context.receive_version_bundle()
    except SpeckleException as e:
        automate_context.mark_run_failed(
            "Could not receive this version as a bundle. The IFC exporter reads "
            f"bundle versions only. Detail: {e}"
        )
        return

    with model:
        print(f"\nReceived {len(model.objects)} objects, units={model.units!r}\n")
        ifc, stats = export_model(
            model,
            project_name=function_inputs.IFC_PROJECT_NAME,
            site_name=function_inputs.IFC_SITE_NAME,
            building_name=function_inputs.IFC_BUILDING_NAME,
        )

    print(f"\n{'=' * 60}")
    stats.print()
    print(f"{'=' * 60}\n")

    if stats.exported == 0:
        automate_context.mark_run_failed(
            "No exportable geometry found in this version, so no IFC file was written."
        )
        return

    zip_path = write_zipped_ifc(ifc, function_inputs.file_name)
    try:
        blob_id = automate_context.store_file_result(zip_path)
    except Exception as e:
        automate_context.mark_run_failed(f"Could not store the IFC file: {e}")
        return
    # The app's run details show no attachments (ENG-11525), so the status
    # message carries the link.
    url = file_result_url(automate_context.automation_run_data, blob_id)
    print(f"Stored file result {zip_path.name}: {url}")
    automate_context.mark_run_success(
        f"Exported {stats.exported} elements. Download the result file: {url}"
    )


def file_result_url(run_data, blob_id: str) -> str:
    """Browser download link for a file stored with store_file_result."""
    server = run_data.speckle_server_url.rstrip("/")
    return f"{server}/api/stream/{run_data.project_id}/blob/{blob_id}"


def write_zipped_ifc(ifc, file_name: str, directory: Path = Path(".")) -> Path:
    """Write ``<file_name>_<timestamp>.ifc`` and return the path of its zip."""
    stem = Path(file_name).stem if file_name.lower().endswith(".ifc") else file_name
    stem = f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    ifc_path = directory / f"{stem}.ifc"
    zip_path = directory / f"{stem}.zip"
    ifc.write(str(ifc_path))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ifc_path, arcname=ifc_path.name)
    print(f"IFC written: {ifc_path} (zipped: {zip_path})")
    return zip_path


if __name__ == "__main__":
    # Pass the function reference, do not invoke it.
    execute_automate_function(automate_function, FunctionInputs)
