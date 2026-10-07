## 2.6.0 - 2026-10-07
Use any AI you like, longer answers, and screenshots that work on a Mac.

- **Any AI provider.** Settings › AI assistant now takes a key from Anthropic (Claude), OpenAI (ChatGPT), Google
  (Gemini), xAI (Grok), DeepSeek, Mistral, Groq, Perplexity, Together, OpenRouter (hundreds of models with one key),
  a free local model through Ollama, or any other OpenAI-compatible server. Paste a key and the provider is detected
  from it.
- **Always the newest models.** Instead of a fixed list, the app asks your provider for its current models and picks
  the best one automatically. You can choose another or type any model name.
- **Longer answers, longer memory.** Answers can now run to 16,000 tokens by default (32,000 on *Maximum*), the chat
  remembers the last 40 messages, and the AI can read scripts up to 60,000 characters. You only pay for what's used.
  With Claude, the script and instructions are cached between questions, so follow-ups are cheaper and faster.
- **Smarter fallbacks.** If a model can't see images it answers from your text and says so; if it only allows shorter
  answers, the app retries with a smaller limit instead of failing.
- **Key check for every provider.** The key is tested as you paste it (free where the provider allows), with a clear
  reason when it's rejected.
- **Mac: screenshots and the phone's Screen view work.** They used an old macOS capture call that returns a gray
  picture on recent macOS. They now use macOS's own screen capture, ask for the Screen Recording permission, and
  open the right System Settings page if it's off.
- **The Windows installer closes a running Glass Prompter** before updating, so "DeleteFile failed; code 5" can't happen.
- Settings is laid out in three columns, so it fits on a laptop screen.
