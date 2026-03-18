# Manual Test Prompts

Copy-paste these into the agent terminal to verify tools are working.

---

## 1. run_command — basic (confirms the core bug is fixed)

```
Run the command "df -h" and show me the output
```

```
What's the current memory usage? Run "free -h" to check
```

```
Run "ip a" and show me the network interfaces
```

```
Run "uname -a" and tell me the OS and kernel version
```

---

## 2. run_command — chained

```
Check disk usage with "df -h", then show the top 5 largest directories under /opt with "du -sh /opt/* 2>/dev/null | sort -rh | head -5"
```

---

## 3. run_code — Python execution

```
Run this Python code and give me the result: print([x**2 for x in range(10)])
```

```
Use Python to calculate the first 10 Fibonacci numbers and print them
```

---

## 4. read_file / write_file — filesystem

```
Create a file at /opt/dolOS/data/test.txt with the content "agent test 123", then read it back and confirm the contents
```

---

## 5. search_memory — memory recall

Send this first:
```
Remember that my preferred output format is always JSON
```

Then in a new turn:
```
What output format do I prefer?
```

---

## 6. create_skill — self-extension

```
Create a new skill called "get_uptime" that runs the "uptime" command and returns the result
```

Then test it:
```
Use the get_uptime skill to check how long this machine has been running
```

---

## 7. Multi-step tool use

```
Find all .py files in /opt/dolOS/skills, then read the contents of system.py and summarise what tools it provides
```

---

## Expected behaviour for all prompts

- Agent calls the appropriate tool (visible in logs as `[REACT]` or native tool_calls)
- Returns **real output** from the tool, not invented/simulated text
- Does NOT say "I cannot execute shell commands" or "run this in your terminal"
