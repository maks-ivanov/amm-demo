# Algorand AMM Demo

This demo is an on-chain automated market maker using smart contracts on the Algorand blockchain. 
This AMM facilitates swaps between tokens using the constant product formula and charges a configurable fee.

Users are able to supply liquidity, for which they receive pool tokens that entitle them to redeem the corresponding portion of pool reserves plus accrued fees.
First liquidity provider can supply tokens in any proportion. Subsequent users supply tokens at current market rate.

Providers can withdraw liquidity at current market rate, i.e. the current ratio of the reserve.

## TODO
* Features:
    * Limit fill or kill swaps
    * "Market buy" orders - specify the exact amount of other token desired, execute at market price
* Maintenance
  * Simplify contract code
  * Tests
  * Docs

## Usage

The file `amm/operations.py` provides a set of functions that can be used to create and interact
with AMM. See that file for documentation.

## Development Setup

This repo requires Python 3.6 or higher. We recommend you use a Python virtual environment to install
the required dependencies.

Set up venv (one time):
 * `python3 -m venv venv`

Active venv:
 * `. venv/bin/activate` (if your shell is bash/zsh)
 * `. venv/bin/activate.fish` (if your shell is fish)

Install dependencies:
* `pip install -r requirements.txt`

Run tests:
* First, start an instance of [sandbox](https://github.com/algorand/sandbox) (requires Docker): `./sandbox up nightly`
* `pytest`
* When finished, the sandbox can be stopped with `./sandbox down`

Format code:
* `black .`
