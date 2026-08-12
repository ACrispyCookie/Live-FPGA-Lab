import pytest

from fpga_demo_platform.demos import GPGPU_NBODY, get_demo, list_demos


def test_only_gpgpu_demo_is_registered_initially():
    demos = list_demos()

    assert demos == [GPGPU_NBODY]
    assert get_demo("gpgpu-nbody").board == "HelloFPGA ZYNQ7000"


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
