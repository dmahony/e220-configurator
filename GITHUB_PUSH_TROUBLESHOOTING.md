# GitHub Push Troubleshooting

## Error Encountered
```
remote: Permission to dmahony/e220-configurator.git denied to dmahony.
fatal: unable to access 'https://github.com/dmahony/e220-configurator.git/': The requested URL returned error: 403
```

## Diagnosis
Even with a valid Personal Access Token (PAT), push is being denied. This indicates:
1. Token may lack `repo` scope
2. Token may have IP or time restrictions
3. Repository permissions issue

## Commit Ready to Push
```
Hash: f8c2341
Author: Dan Mahony <dan@radxa.local>
Message: Complete binary register protocol implementation and audit fixes
Branch: main
Status: 1 commit ahead of origin/main
```

## Solutions (in order of preference)

### Solution 1: Verify Token Scopes
1. Go to https://github.com/settings/tokens
2. Click on your token
3. Ensure these scopes are checked:
   - `repo` (Full control of private repositories)
   - `workflow` (Update GitHub Action workflows) - optional
4. If scopes are missing, create a new token with proper scopes

### Solution 2: Try SSH Instead
If HTTPS with token is problematic, try SSH:

```bash
# Check if SSH key is set up
ssh -T git@github.com

# If that fails, set up SSH keys first:
# https://docs.github.com/en/authentication/connecting-to-github-with-ssh

# Then push via SSH:
cd /tmp/e220-configurator
git remote set-url origin git@github.com:dmahony/e220-configurator.git
git push origin main
```

### Solution 3: Force Push with New Token
1. Create a NEW Personal Access Token with only `repo` scope
2. Use it with:
```bash
cd /tmp/e220-configurator
git push https://dmahony:<NEW_TOKEN>@github.com/dmahony/e220-configurator.git main
```

### Solution 4: Manual Merge via GitHub Web UI
1. Fork the repository to ensure you have push access
2. Create a pull request with your changes
3. Merge via GitHub web interface

### Solution 5: Use GitHub CLI (gh)
```bash
# Install GitHub CLI if not already installed
# https://cli.github.com/

# Authenticate
gh auth login

# Push
cd /tmp/e220-configurator
gh repo sync
git push origin main
```

## Backup of Your Commit

Your commit has been bundled for safekeeping:

```
File: /tmp/e220-configurator-f8c2341.bundle
Size: 58 KB

To restore later:
git clone /tmp/e220-configurator-f8c2341.bundle e220-restored
```

## What's in the Commit

### Files
- `e220-configurator.py` - 2038 lines (binary protocol implementation)
- `README.md` - Updated documentation
- `ISSUES_FIXED.md` - Audit trail
- `PUSH_INSTRUCTIONS.md` - Push guide

### Changes
✓ Binary register protocol (0xC1/0xC0/0xC4/0xC2)
✓ Frequency: 900.125 MHz (915MHz variant)
✓ Mode pins: Verified correct
✓ Parameter arrays: No duplicates
✓ CLI args: All fixes applied
✓ Persistence: 0xC4 save command

## Recommended Next Step

**Try SSH** - it's often more reliable than HTTPS for GitHub:

```bash
# 1. Set up SSH if needed
# https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent

# 2. Switch to SSH
cd /tmp/e220-configurator
git remote set-url origin git@github.com:dmahony/e220-configurator.git

# 3. Push
git push origin main -v
```

## Support

If push still fails:
1. Check GitHub repo permissions: https://github.com/dmahony/e220-configurator/settings/access
2. Verify token scopes at: https://github.com/settings/tokens
3. Contact GitHub support if needed

Your local commit (f8c2341) is safe and ready whenever access is restored.

---
Generated: 2026-03-21
Status: Ready to push (just needs authentication fix)
