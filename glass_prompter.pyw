"""Glass Prompter launcher (run from source). The installed app uses the bundled GlassPrompter.exe."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from glassprompter.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
