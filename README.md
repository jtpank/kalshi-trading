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
* run_simulation() does not run in parallel. It is async. This was done for equivalence when launching ws connection to Kalshi for live (PROD) runs. Now we can either 1. refactor so it is entirely parallel on the data sets we use for backtesting. Or 2. Launch a replica ws connection while simulating the live data coming in simultaneously as a websocket connection. This will maintain equivalence but won't let us rapidly test, so is not ideal.