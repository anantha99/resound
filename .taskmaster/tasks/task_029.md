# Task ID: 29

**Title:** Record and Edit Demo Video

**Status:** pending

**Dependencies:** 23, 24, 25, 26, 27, 28

**Priority:** high

**Description:** Record the 3-minute demo video using the prepared scripts, execute all 5 beats, and edit to final cut within 2:45-3:15 runtime.

**Details:**

Recording execution per PRD §4 and Appendix A:

1. **Setup:**
- Recording tool: Loom or OBS
- Resolution: 1920x1080, 30fps
- Audio: External mic preferred, -16 LUFS target
- Script on second monitor or teleprompter app

2. **Recording flow:**
- Beat 1: Hook (0:00-0:20)
  - Title card display
  - Voiceover + fragmented signals image
- Beat 2: Liquid Death live (0:20-1:10)
  - Terminal + dashboard
  - Signal walkthrough
- Beat 3: Extensibility (1:10-2:00)
  - File tree + cp + editor diffs
  - Ridge healthcheck + run
- Beat 4: Architecture (2:00-2:30)
  - Diagram + model swap
- Beat 5: Close (2:30-3:00)
  - Dashboard both brands + closing card

3. **Recording rules (PRD §3.1):**
- One re-take max per beat
- If beat requires more, script is wrong — fix script first
- Pre-cache all slow operations
- No silent screen movement — every click has narration

4. **Editing:**
- Cut dead air > 1.5 seconds
- Smooth transitions between beats
- Add subtitles (Loom auto-generate, manually correct)
- Verify runtime: 2:45-3:15

5. **Export:**
- MP4, 1080p, 30fps
- Stereo audio, -16 LUFS
- Upload to Loom (private share)

6. **Deliverable:**
- Loom share link
- Repo URL in video description

**Test Strategy:**

Video acceptance criteria:
- Runtime between 2:45 and 3:15
- All 5 beats executed per scripts
- Audio is clear, no background noise
- Terminal/dashboard text is legible
- No waiting/loading visible (edited out)
- Subtitles are accurate for product names
- Video is private/password-protected
