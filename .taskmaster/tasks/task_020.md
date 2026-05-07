# Task ID: 20

**Title:** Add LICENSE File

**Status:** pending

**Dependencies:** None

**Priority:** medium

**Description:** Add a LICENSE file to the repository as required by the demo-ready definition in PRD §8.

**Details:**

Per PRD §8: "License file present (MIT or 'all rights reserved' — pick one and own it)."

The README currently states "Proprietary" for License. Create a LICENSE file to match:

**Option A - Proprietary (recommended for hiring pitch):**
```
Copyright (c) 2024 [Your Name]

All rights reserved.

This software and associated documentation files (the "Software") are proprietary
and confidential. Unauthorized copying, distribution, modification, public display,
or public performance of this Software is strictly prohibited.

This Software is provided for evaluation purposes only in connection with employment
discussions with Fulfil.io. No license to use, copy, modify, or distribute this
Software is granted except as explicitly authorized in writing.
```

**Option B - MIT (if open-sourcing later):**
Standard MIT license text.

Recommendation: Use Option A (Proprietary) because:
1. This is a hiring artifact, not an open-source project
2. Protects the work while allowing Fulfil to evaluate
3. Matches the "Proprietary" note already in README

**Test Strategy:**

Verification:
- LICENSE file exists in repo root
- Content is coherent (not placeholder text)
- README.md license note matches LICENSE file content
- `git status` shows LICENSE as tracked
