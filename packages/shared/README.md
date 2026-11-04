# @superagent/shared

Framework-free helpers used by both the web app and the local runner. Nothing in here may
import React, Django, or a network client, so it stays portable and trivially testable.

Candidates as the product grows: path normalisation rules shared with the runner's workspace
guard, cost formatting, and the run-state vocabulary (`queued|running|waiting_approval|...`).
