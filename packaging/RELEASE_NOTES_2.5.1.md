## 2.5.1 - 2026-10-06
Polish for the AI assistant, and a refreshed website.

- The AI chat window now keeps the newest message at the bottom, like any messaging app, and the welcome tip
  disappears as soon as you ask your first question.
- The phone's AI tab says what the assistant can do: answer anything, see your screen, search the web.
- Website: new AI assistant section, phone screen-view images, updated shortcuts (<kbd>A</kbd>, <kbd>S</kbd>),
  comparison table and FAQ (how to turn on the AI, what it costs, what it sees).

## 2.5.0 - 2026-10-05
Your phone can now see your computer screen, and an AI assistant can help you with what's on it.

- **Live screen view on your phone.** The new **Screen** tab in the phone remote shows your computer's screen,
  refreshed about every 1.5 seconds. Tap the picture to open it full size and pinch to zoom. Pause stops the
  updates. The prompter itself never appears in the picture on Windows, because it's hidden from capture.
  - Turn it off with **Settings › Privacy › Phone can view my screen**.
  - On a Mac, allow Glass Prompter in **System Settings › Privacy & Security › Screen Recording** first.
- **AI assistant (bring your own key).** The new **AI** tab is a chat with Claude that can see your current
  screen and the script on the prompter. Ask "what should I say about this slide?" or "write a 20-second intro".
  **Send to prompter** puts any answer straight on the prompter.
  - Add an Anthropic API key in **Settings › AI assistant** and pick a model (Sonnet 5.5 by default).
  - The key stays on your computer, in its own `ai.key` file in your data folder (not in the settings file, so a
    shared settings file or bug report never contains it). You can also set `GLASSPROMPTER_AI_KEY`. The phone never sees it, and requests go only from your computer to
    `api.anthropic.com`. Nothing is sent unless you send a message.
- **AI assistant on the computer too.** Press <kbd>A</kbd> on the prompter (or **⋯ › AI assistant**) for a chat
  window on your PC. It answers any question, not just script ones: it can see your screen, search the web for
  current facts, and send any answer to the prompter. The window stays out of screen shares and out of the
  screenshot Claude sees.
- **Screenshots.** Press <kbd>S</kbd> (or **⋯ › Take screenshot**, or the Screenshot button in the AI window) to save
  a full-resolution PNG to **Pictures › Glass Prompter** and copy it to the clipboard. On the phone, the Screen tab has
  **Save screenshot** (full resolution) and **Ask AI about this**.
- **Everything is hidden from screenshots and screen shares (Windows 10 2004+, macOS 14 and earlier).** Before, only
  the prompter and Glass Prompter's own dialogs were. Now a privacy guard also hides message boxes, the file picker,
  menus (including the tray menu), tooltips and the AI window, the moment they appear. Audited window by window on
  Windows: 8/8 hidden. The prompter itself still follows **Hide from screen share** (<kbd>C</kbd>).
- New API endpoints: `GET /api/v1/features`, `GET /api/v1/screen.jpg` (`?full=1` for full resolution),
  `POST /api/v1/ai/chat`.
- The `--e2e` audit and the phone test now cover the screen view and the AI chat.
