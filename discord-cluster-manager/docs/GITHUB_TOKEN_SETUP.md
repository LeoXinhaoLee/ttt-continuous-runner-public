# How to Create a GitHub Personal Access Token

A GitHub Personal Access Token (PAT) is required to set up a self-hosted GitHub Actions runner.

## Step-by-Step Instructions

### 1. Go to GitHub Token Settings

Navigate to: **https://github.com/settings/tokens**

Or:
1. Click your profile picture (top right) → **Settings**
2. Scroll down in the left sidebar → **Developer settings**
3. Click **Personal access tokens** → **Tokens (classic)**

### 2. Generate a New Token

1. Click **Generate new token** → **Generate new token (classic)**
2. You may be prompted for your GitHub password

### 3. Configure the Token

1. **Note**: Give it a descriptive name (e.g., "Runner Setup Token for mla-decode")
2. **Expiration**: 
   - Recommended: 90 days or less for security
   - You can set it to "No expiration" but this is less secure
3. **Select scopes** (permissions):
   - ✅ **`repo`** - Full control of private repositories
     - This includes: `repo:status`, `repo_deployment`, `public_repo`, `repo:invite`, `security_events`
   - ✅ **`workflow`** - Update GitHub Action workflows
   - You may see these under "Repository permissions" section

### 4. Generate and Copy

1. Scroll down and click **Generate token**
2. **IMPORTANT**: Copy the token immediately! It looks like: `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
3. You won't be able to see it again after you leave this page
4. If you lose it, you'll need to generate a new one

### 5. Use the Token

When the setup script asks for "GitHub personal access token", paste the token you just copied.

## Token Format

GitHub tokens start with:
- `ghp_` for classic personal access tokens
- `gho_` for OAuth tokens
- `ghu_` for user-to-server tokens
- `ghs_` for server-to-server tokens

For runner setup, you need a classic token (`ghp_`).

## Security Notes

- **Never commit tokens to git repositories**
- **Don't share tokens publicly**
- **Set expiration dates** and rotate tokens regularly
- **Use the minimum required permissions** (just `repo` and `workflow` for runner setup)
- **Revoke tokens** if they're compromised or no longer needed

## Troubleshooting

- **"Token is invalid"**: Make sure you copied the entire token (they're long!)
- **"Insufficient permissions"**: Ensure you selected `repo` and `workflow` scopes
- **"Token expired"**: Generate a new token with a longer expiration
- **"Token not found"**: You may have navigated away from the page - generate a new one

## Alternative: Fine-Grained Personal Access Token

GitHub also offers "Fine-grained personal access tokens" (beta). For runner setup, you can use either:
- **Classic tokens** (recommended for simplicity)
- **Fine-grained tokens** (more granular permissions, but more complex setup)

For the setup script, classic tokens work perfectly.

