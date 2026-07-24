# M21 Loop external scheduler examples

These are user-installed examples that invoke one ForgeAgent Loop run or resume.
ForgeAgent does not provide a scheduler daemon. Configure only one trigger for a
checkpoint at a time: cross-process overlap is not coordinated by the CLI.

The commands intentionally contain no credentials. Set service credentials in the
user's normal environment/configuration, not in a scheduler command line.

## cron

Install this line with the user's crontab after replacing paths and `LOOP_ID`:

```cron
0 * * * * cd /path/to/project && /path/to/uv run forgeagent loop --resume LOOP_ID
```

## launchd

Use a user-installed plist whose `ProgramArguments` runs one resume:

```xml
<array>
  <string>/path/to/uv</string>
  <string>run</string>
  <string>forgeagent</string>
  <string>loop</string>
  <string>--resume</string>
  <string>LOOP_ID</string>
</array>
```

## systemd

Use a user-installed service plus timer. The service's command is one resume:

```ini
[Service]
WorkingDirectory=/path/to/project
ExecStart=/path/to/uv run forgeagent loop --resume LOOP_ID
```

Avoid a timer interval shorter than a possible Loop duration. No scheduler daemon is
started by ForgeAgent, and overlapping resumes can race on the same checkpoint.

## HTTP submission

An authenticated local client can create a Loop with the documented `POST /tasks`
body, then poll its task id. A resume sends only `mode` and `resume_loop_id`; paths,
sandbox tier, credentials and frozen budgets remain server-owned.
