# DVD Logo demo bitstream

Place the generated FPGA bitstream here as:

```text
dvd_logo.bit
```

The demo definition detects that file when `web-api` starts. Until it exists,
the demo still exposes the HDMI capture runtime but skips FPGA programming.
Restart `web-api` after adding or replacing the bitstream.

You can use another in-container path by setting `DVD_LOGO_BITSTREAM`.

Source project: <https://github.com/ACrispyCookie/DVD-Logo-FPGA>
