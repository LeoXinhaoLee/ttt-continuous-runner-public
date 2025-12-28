# Setting Up Folder Permissions for Runner User

To allow the runner user to access the repository folder with all permissions (like root), you have several options.

## Option 1: Change Ownership (Recommended for Development)

Change the entire folder ownership to the runner user:

```bash
# As root, change ownership recursively
chown -R runner:runner /root/ttt-continuous-main

# Verify ownership changed
ls -la /root/ttt-continuous-main
```

**Pros:**
- Simple and straightforward
- Runner user has full control

**Cons:**
- Root loses ownership (though root can always change it back)
- If multiple users need access, this isn't ideal

## Option 2: Add User to Group and Set Group Permissions

Create a shared group and give group ownership:

```bash
# As root, create a group (if it doesn't exist)
groupadd dev-group  # or use an existing group

# Add runner user to the group
usermod -aG dev-group runner

# Change group ownership of the folder
chgrp -R dev-group /root/ttt-continuous-main

# Give group read, write, execute permissions
chmod -R g+rwx /root/ttt-continuous-main

# Ensure new files inherit group ownership
chmod g+s /root/ttt-continuous-main
```

**Pros:**
- Multiple users can be in the group
- Root retains ownership

**Cons:**
- More complex setup

## Option 3: Use ACLs (Access Control Lists) - Most Flexible

Give the runner user full permissions via ACLs while keeping root as owner:

```bash
# Install ACL tools (if not already installed)
# On Ubuntu/Debian:
apt-get install -y acl

# Give runner user full permissions recursively
setfacl -R -m u:runner:rwx /root/ttt-continuous-main

# Set default ACLs so new files inherit permissions
setfacl -R -d -m u:runner:rwx /root/ttt-continuous-main

# Verify ACLs
getfacl /root/ttt-continuous-main
```

**Pros:**
- Root keeps ownership
- Can add multiple users easily
- Very flexible

**Cons:**
- Requires ACL support on filesystem
- Slightly more complex

## Option 4: Move Repository to Shared Location

Move the repository to a location accessible to all users:

```bash
# As root, move to a shared location
mv /root/ttt-continuous-main /opt/ttt-continuous-main

# Change ownership
chown -R runner:runner /opt/ttt-continuous-main

# Or use group permissions
chgrp -R dev-group /opt/ttt-continuous-main
chmod -R g+rwx /opt/ttt-continuous-main
```

Then update paths in scripts accordingly.

## Recommended Approach

For a single runner user setup, **Option 1 (change ownership)** is simplest:

```bash
chown -R runner:runner /root/ttt-continuous-main
```

If you need multiple users, use **Option 3 (ACLs)**:

```bash
apt-get install -y acl
setfacl -R -m u:runner:rwx /root/ttt-continuous-main
setfacl -R -d -m u:runner:rwx /root/ttt-continuous-main
```

## Verifying Permissions

After setting up permissions, verify as the runner user:

```bash
# Switch to runner user
su - runner

# Check if you can access the folder
cd /root/ttt-continuous-main
ls -la

# Try creating a test file
touch test_file.txt
rm test_file.txt

# If all works, permissions are set correctly
```

