# Troubleshooting GitHub Actions Runner 404 Error

If you get a 404 error when configuring the runner:
```
Http response code: NotFound from 'POST https://api.github.com/actions/runner-registration'
Response status code does not indicate success: 404 (Not Found).
```

## Common Causes and Solutions

### 1. Repository URL Format is Wrong

**Problem:** You entered the full git URL instead of just `owner/repo`

**Solution:**
- ✅ Correct: `mertyg/ttt-continuous`
- ❌ Wrong: `git@github.com:mertyg/ttt-continuous.git`
- ❌ Wrong: `https://github.com/mertyg/ttt-continuous.git`
- ❌ Wrong: `github.com/mertyg/ttt-continuous`

**Check:** Verify the repository URL format before running the script

### 2. Repository Doesn't Exist or You Don't Have Access

**Problem:** The repository doesn't exist, is private and you don't have access, or the name is misspelled

**Solution:**
1. Verify the repository exists: Visit `https://github.com/owner/repo` in a browser
2. Make sure you're logged in and can see the repository
3. For private repos, ensure your GitHub account has access
4. Double-check spelling (case-sensitive!)

**Test:** Try accessing the repository settings: `https://github.com/owner/repo/settings/actions/runners`

### 3. Token Permissions Are Insufficient

**Problem:** The GitHub token doesn't have the required scopes

**Solution:**
1. Go to: https://github.com/settings/tokens
2. Find your token and check its scopes
3. Make sure it has:
   - ✅ `repo` (Full control of private repositories)
   - ✅ `workflow` (Update GitHub Action workflows)
4. If missing, create a new token with these scopes

**Verify token works:**
```bash
# Test the token can access the repository
curl -H "Authorization: token YOUR_TOKEN" https://api.github.com/repos/owner/repo
# Should return repository info, not 404
```

### 4. Token is Invalid or Expired

**Problem:** The token was deleted, expired, or is incorrect

**Solution:**
1. Generate a new token: https://github.com/settings/tokens
2. Make sure to copy it completely (tokens are long!)
3. Try again with the new token

### 5. Organization/Repository Settings Block Runner Registration

**Problem:** Organization policies or repository settings prevent runner registration

**Solution:**
1. **Repository-level runners:** You need **Admin** access to the repository (not just write access)
   - Check your access level: Go to repository → Settings → Collaborators & teams
   - You should see your role listed as "Admin"
   - Being a "Collaborator" with "Write" access is NOT sufficient for runner registration
2. Go to repository Settings → Actions → Runners
3. Check if there are any restrictions
4. For organizations, check organization Settings → Actions → Runners for policies
5. **You don't need to be the owner**, but you DO need Admin permissions on the repository

## Step-by-Step Verification

Run these checks before configuring the runner:

### Step 1: Verify Repository Format
```bash
# Your repository should be in format: owner/repo
echo "Repository: owner/repo"
# Example: mertyg/ttt-continuous
```

### Step 2: Test Repository Access
Visit in browser: `https://github.com/owner/repo`
- Should load successfully
- Should show repository contents
- For private repos, must be logged in

### Step 3: Test Token Access
```bash
# Replace with your values
OWNER="your-username-or-org"
REPO="your-repo-name"
TOKEN="your-token-here"

# Test API access
curl -H "Authorization: token $TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     https://api.github.com/repos/$OWNER/$REPO

# Should return JSON with repository info, not 404
```

### Step 4: Check Token Scopes
```bash
# Check what scopes your token has
curl -H "Authorization: token $TOKEN" \
     https://api.github.com/user \
     | grep -i scope

# Or use GitHub CLI
gh auth status
```

### Step 5: Verify Runner Registration Endpoint
The runner registration endpoint should be accessible:
```bash
# This endpoint should exist for your repo
curl -H "Authorization: token $TOKEN" \
     https://api.github.com/repos/$OWNER/$REPO/actions/runners/registration-token \
     -X POST
```

## Getting a Fresh Registration Token

If you need to get a fresh registration token manually:

1. Go to: `https://github.com/owner/repo/settings/actions/runners`
2. Click "New self-hosted runner"
3. Copy the registration token shown
4. Use it in the config.sh command

Or via API:
```bash
curl -X POST \
  -H "Authorization: token YOUR_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/owner/repo/actions/runners/registration-token
```

## Still Having Issues?

1. Double-check all inputs (repository name, token)
2. Try creating a new token with full `repo` scope
3. Verify you can access the repository in a web browser
4. Check if the repository has Actions enabled: Settings → Actions → General
5. For organizations, verify you have admin rights or runner registration permissions

