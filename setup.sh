#!/usr/bin/env bash
set -e

echo "==> Creating virtual environment..."
python3.8 -m venv venv

echo "==> Activating venv and installing dependencies..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Creating .env from template..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "     .env created — fill in your API keys before running."
else
    echo "     .env already exists — skipping."
fi

echo "==> Creating data and logs directories..."
mkdir -p data logs

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. Edit .env with your keys (OPENAI_API_KEY, FB_APP_ID, FB_APP_SECRET, FB_PAGE_ID, FB_USER_TOKEN)"
echo "  2. Edit config/sources.yaml with your news sources and CSS selectors"
echo "  3. Edit config/prompts.yaml to customise the criteria and writing style"
echo "  4. Run once to get FB tokens:  ./venv/bin/python refresh_token.py"
echo "  5. Test the pipeline:          ./venv/bin/python main.py --dry-run"
echo "  6. Run for real:               ./venv/bin/python main.py"
echo ""
echo "Cron examples (add via 'crontab -e'):"
echo "  # Run pipeline every 6 hours:"
echo "  0 */6 * * *  cd $(pwd) && ./venv/bin/python main.py >> logs/cron.log 2>&1"
echo ""
echo "  # Refresh FB token on the 1st of every month:"
echo "  0 0 1 * *    cd $(pwd) && ./venv/bin/python refresh_token.py >> logs/token_refresh.log 2>&1"
