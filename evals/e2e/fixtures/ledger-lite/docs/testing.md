# Running the tests

The tests load sample CSV files from the directory named by the `SAMPLE_DATA_DIR` environment variable. Without it
every test stops during setup with an error that points here.

```bash
export SAMPLE_DATA_DIR=testdata
python3 -m pytest -q
```

`testdata/` in the repository holds the March sample journal and statement. Do not edit these files to make a test
pass; they describe the expected inputs.
