import pytest

from fpga_demo_platform.demos import get_demo, list_demos


def test_discovers_gpgpu_demo_from_demo_folder_definition():
    demos = list_demos()

    assert [demo.id for demo in demos] == ["gpgpu-nbody"]
    demo = get_demo("gpgpu-nbody")
    assert demo.board == "HelloFPGA ZYNQ7000"
    assert demo.root.name == "gpgpu-nbody"
    assert demo.definition_path.name == "demo_definition.py"


def test_gpgpu_input_defaults_and_validation():
    demo = get_demo("gpgpu-nbody")

    assert demo.validate_input({}) == {
        "dataset": "default",
        "steps_per_frame": 1,
        "fps": 12.0,
    }
    assert demo.validate_input({"dataset": "wide", "steps_per_frame": 8, "fps": 24}) == {
        "dataset": "wide",
        "steps_per_frame": 8,
        "fps": 24.0,
    }

    with pytest.raises(ValueError, match="unsupported input"):
        demo.validate_input({"bodies": 128})
    with pytest.raises(ValueError, match="steps_per_frame"):
        demo.validate_input({"steps_per_frame": 0})
