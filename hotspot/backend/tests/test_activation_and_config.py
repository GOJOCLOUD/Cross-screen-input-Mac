import json
import os
import tempfile
import unittest

from routes import activation, mouse_config


class ActivationAndConfigContractTests(unittest.TestCase):
    def test_activation_flag_coerce_contract(self):
        self.assertTrue(activation._coerce_activated_flag(True))
        self.assertTrue(activation._coerce_activated_flag("true"))
        self.assertTrue(activation._coerce_activated_flag("1"))
        self.assertFalse(activation._coerce_activated_flag(False))
        self.assertFalse(activation._coerce_activated_flag("false"))
        self.assertFalse(activation._coerce_activated_flag("0"))
        self.assertFalse(activation._coerce_activated_flag(None))

    def test_activation_save_uses_atomic_replace_and_loads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_file = activation.ACTIVATION_FILE
            try:
                activation.ACTIVATION_FILE = os.path.join(tmp, "activation.json")
                payload = {"activated": False, "uuid": "u", "license_blob": ""}
                self.assertTrue(activation.save_activation_status(payload))
                loaded = activation.load_activation_status()
                self.assertIn("activated", loaded)
                self.assertFalse(loaded.get("activated"))
            finally:
                activation.ACTIVATION_FILE = old_file

    def test_mouse_buttons_data_repair_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = mouse_config.DATA_DIR
            old_json = mouse_config.JSON_FILE
            try:
                mouse_config.DATA_DIR = tmp
                mouse_config.JSON_FILE = os.path.join(tmp, "mouse_buttons.json")
                with open(mouse_config.JSON_FILE, "w", encoding="utf-8") as f:
                    json.dump({"buttons": ["bad", {"id": "ok", "action": "ctrl+c"}]}, f, ensure_ascii=False)
                repaired = mouse_config.load_buttons_data()
                self.assertIsInstance(repaired.get("buttons"), list)
                self.assertEqual(len(repaired["buttons"]), 1)
                self.assertEqual(repaired["buttons"][0]["id"], "ok")
            finally:
                mouse_config.DATA_DIR = old_dir
                mouse_config.JSON_FILE = old_json


if __name__ == "__main__":
    unittest.main()
