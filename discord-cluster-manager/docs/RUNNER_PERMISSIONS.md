# GitHub Actions Runner Permissions Requirements

## Can I Set Up a Runner as a Collaborator?

**Short answer:** Yes, but you need **Admin** permissions on the repository, not just Write access.

## Required Permissions

### For Repository-Level Runners

To register a self-hosted runner on a repository, you need:

1. **Repository Access Level: Admin**
   - ❌ Owner-only: No, collaborators can do it
   - ❌ Write access: No, this is not sufficient
   - ✅ Admin access: Yes, this is sufficient
   - ✅ Owner: Yes, always works

2. **GitHub Token with Required Scopes:**
   - ✅ `repo` scope (Full control of private repositories)
   - ✅ `workflow` scope (Update GitHub Action workflows)

### For Organization-Level Runners

To register an organization-level runner, you need:
- Organization owner, OR
- Organization admin with runner management permissions

## How to Check Your Permission Level

### Method 1: Via Repository Settings

1. Go to: `https://github.com/OWNER/REPO/settings/access`
2. Look for your username in "Collaborators & teams"
3. Your role should show as **"Admin"** (not "Write" or "Read")

### Method 2: Via Repository Settings → Actions → Runners

1. Go to: `https://github.com/OWNER/REPO/settings/actions/runners`
2. If you can see "New self-hosted runner" button and can manage runners, you have sufficient permissions
3. If you get "You don't have permission" or can't access this page, you need Admin access

### Method 3: Via GitHub API

```bash
# Test if you can access runner registration endpoint
curl -H "Authorization: token YOUR_TOKEN" \
     https://api.github.com/repos/OWNER/REPO/actions/runners/registration-token \
     -X POST

# If you get 403 Forbidden, you don't have Admin access
# If you get 404 Not Found, repository might not exist or token is wrong
# If you get JSON response with a token, you have the right permissions
```

## Getting Admin Access

If you only have Write access and need Admin:

1. **Ask the repository owner:**
   - Go to repository → Settings → Collaborators & teams
   - Click "Add people" or modify your existing role
   - Change your role from "Write" to "Admin"

2. **For organization repositories:**
   - Ask an organization owner to grant you Admin access
   - Or ask them to set up the runner for you

## Token Permissions vs Repository Permissions

Important distinction:
- **Token scopes** (`repo`, `workflow`) - These are permissions your token has
- **Repository access level** (Admin, Write, Read) - These are your account's permissions on the repo

You need BOTH:
- ✅ A token with `repo` and `workflow` scopes
- ✅ Admin access to the repository (or be the owner)

## Summary

| Role | Can Register Runner? |
|------|---------------------|
| Repository Owner | ✅ Yes |
| Repository Admin | ✅ Yes |
| Repository Write | ❌ No |
| Repository Read | ❌ No |
| Organization Owner | ✅ Yes (org-level) |
| Organization Admin | ✅ Yes (if permitted) |

**If you're getting a 404 error and you're a collaborator:**
1. Check if you have Admin access (not just Write)
2. If you only have Write access, ask the owner to upgrade you to Admin
3. Or ask the owner to set up the runner for you

