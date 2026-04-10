# README

## Setup

Create a `.env` file in the project root with the following values:

```env
PROD_KEYID='key-goes-here'
PROD_KEYFILE='path-to-priv.key'
```

Create a configuration file that selects whether the application should run in **simulated** mode or **real** mode.

## Install dependencies

```bash
uv sync
```

## Run the application

```bash
uv run main.py
```

## Notes

* Make sure the private key path in `PROD_KEYFILE` points to a valid key file on your machine.
* Double-check that your configuration file is set to the correct environment before running the app.
