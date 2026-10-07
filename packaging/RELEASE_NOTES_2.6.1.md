## 2.6.1 - 2026-10-07
Small fixes to the AI assistant and Mac screenshots.

- **Switching AI provider just works.** Changing provider in Settings forgets the old provider's model, and a model
  name from one provider is never sent to another (for example a Claude model to Gemini).
- **Retired models don't break the assistant.** If a provider retires its default model, the app switches to that
  provider's newest model instead of showing an error. A model you typed yourself is never swapped silently.
- **Mac: clearer help when a screenshot comes back gray.** An app update can reset the Screen Recording permission;
  the app now says to switch Glass Prompter off and on in System Settings, then reopen it.
- **Fewer false alarms:** a mostly white slide is no longer mistaken for a blank capture.
