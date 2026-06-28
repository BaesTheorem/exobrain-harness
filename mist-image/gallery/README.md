# gallery (gitignored)

Default output folder for `mist-image`. Generated images land here instead of
`~/Downloads`, and the MIST Console renders them inline (it already serves the
harness root via its `/file` route), so you download only the keepers from the
lightbox. The images themselves are gitignored; this README is the only tracked
file. Override the location with `--dir` or `$MIST_IMAGE_DIR`.
