import json
import os

#gpt generated :)
class ConfigUtils:
    @staticmethod
    def save_config(config: dict, filename: str):
        """Saves the given config dictionary to a JSON file."""
        try:
            with open(filename, "w") as f:
                json.dump(config, f, indent=4)
            print(f"Configuration saved to {filename}")
        except Exception as e:
            print(f"Error saving configuration to {filename}: {e}")

    @staticmethod
    def load_config(filename: str) -> dict:
        """Loads configuration from a JSON file if it exists."""
        if os.path.exists(filename):
            try:
                with open(filename, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading configuration from {filename}: {e}")
        return {}  # Return an empty dictionary if loading fails or file doesn't exist
