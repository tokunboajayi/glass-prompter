---
name: glass-prompter-scripts
description: Use when writing, rewriting or timing a script meant to be read aloud on camera (video call, interview answer, pitch, demo, YouTube intro, presentation) and when sending a script to the Glass Prompter teleprompter app through its local API or OneDrive drop folder.
triggers: [teleprompter, script, glass prompter, speech, pitch, talking points, read aloud, video script, interview answer, rehearsal]
---

Glass Prompter reads plain text with three markers, each on its own line:

| Marker | Effect |
|---|---|
| `# Heading` | Section: amber label and a jump point (PgUp/PgDn, phone). Not spoken. |
| `[PAUSE]` | Scrolling stops here until play is pressed. Not spoken. |
| `[ANY CUE]` | Stage direction shown in amber caps, e.g. `[SMILE]`, `[SHOW SLIDE 3]`. Not spoken. |

## Writing rules

- Write for the ear: sentences of 8-18 words, one idea each, contractions, no parentheses, no bullet lists.
- Spell out what must be said: "eighteen percent", "Q3" becomes "third quarter", "e.g." becomes "for example". Voice Follow matches spoken words, so digits and symbols should be written as words.
- Break paragraphs at breath points. Put `[PAUSE]` before a question to the audience or a key number.
- Start each logical part with a `# Heading` so the speaker can jump between sections, especially for interviews with answers to likely questions.
- Keep cues to one or two per section.
- Size to the slot: target pace is 150 wpm (comfortable range 130-165). Words = minutes x 150. A 60-second intro is about 150 words.
- Avoid words the Rehearsal Coach flags as fillers unless they're intentional: um, uh, like, basically, actually, literally, you know.

## Example

```text
# Opening
Good morning everyone, and thank you for making the time.
Today I'll walk you through three things: where we are, what we learned, and what's next.
[PAUSE]
# Results
Revenue grew eighteen percent this quarter.
[SHOW CHART]
That growth came almost entirely from returning customers.
# Ask
We're asking for one decision today: approve the pilot for the spring.
```

## Delivering a script to the prompter

The local API is only reachable from the same Wi-Fi as the PC running Glass Prompter (default port 8765, PIN from the app: press P).

```python
import json, urllib.request

BASE = "http://192.168.1.20:8765/api/v1"          # address shown in the app's phone dialog

def call(path, body=None, token=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": "Bearer " + token} if token else {})})
    return json.load(urllib.request.urlopen(req))

token = call("/session", {"pin": "123456"})["token"]
call("/scripts", {"title": "Board update", "body": SCRIPT, "load": True}, token)   # save and show it
call("/control", {"action": "voice"}, token)                                        # optional: Voice Follow
```

Other actions for `/control`: play, restart, faster, slower, back, ahead, bigger, smaller, hide, ghost, next_section, prev_section, read_aloud.

The API won't be reachable from the cloud (for example a Val Town val), so write the script to the user's OneDrive drop folder instead: `Documents/Glass Prompter/<title>.txt`. The app imports it into the library and loads it within a few seconds.
