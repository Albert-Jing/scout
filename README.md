# Scout

A research agent: give it a target ("seed VCs in SF who led AI dev-tools rounds this year") and it returns a sourced list of people, why each fits, their public contact channels, and a drafted first line.

Work in progress. Full write-up coming.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your Anthropic API key in .env
```
