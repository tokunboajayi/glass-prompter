# Third-party components

Glass Prompter's own code is under the [MIT License](LICENSE). The installers also bundle the components below,
each under its own license.

| Component | Used for | License |
|---|---|---|
| [Qt for Python (PySide6)](https://www.qt.io/qt-for-python) | User interface | LGPL-3.0 |
| [Vosk](https://github.com/alphacep/vosk-api) and the `vosk-model-small-en-us-0.15` model | Offline speech recognition (Voice Follow) | Apache-2.0 |
| [Piper](https://github.com/rhasspy/piper) | Read Aloud neural voices | MIT |
| Piper voice models (e.g. `en_US-lessac`) | Read Aloud voices | See each voice's `MODEL_CARD` on [Hugging Face](https://huggingface.co/rhasspy/piper-voices) |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Runs the voice models | MIT |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | Microphone and speaker audio | MIT |
| [qrcode](https://github.com/lincolnloop/python-qrcode) | Phone-remote QR code | BSD |
| [PyObjC](https://github.com/ronaldoussoren/pyobjc) (macOS only) | Native macOS window features | MIT |
| [Inter](https://rsms.me/inter/) | Typeface | SIL Open Font License 1.1 (see `glassprompter/fonts/LICENSE-Inter.txt`) |
