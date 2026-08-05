# Client Logo Implementation - Testing Guide

## Implementation Summary

The client logo feature loads logos dynamically from GitHub, ensuring availability in both development and production environments.

### 1. Directory Structure
- Location: `dashboard/logos/` (committed to Git repository)
- Naming convention: `{client_lowercase}.png`
- Examples:
  - `dashboard/logos/enex.png`
  - `dashboard/logos/cda.png`
  - `dashboard/logos/emin.png`

### 2. Logo Loading Mechanism

Logos are loaded from GitHub raw content URLs:
```
https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos/{client}.png
```

This approach:
- ✅ Works in production without server-side file serving
- ✅ Works in local development
- ✅ Requires logos to be committed to the Git repository
- ✅ Uses the `dev` branch for latest logos

### 3. Modified Files

#### `dashboard/layout.py`
- Added client logo `<img>` element with ID `client-logo-img` next to CODDI logo
- Positioned in the left branding section of the header
- Set to hidden by default

#### `dashboard/callbacks/navigation_callbacks.py`
- Added callback to update client logo based on `client-selector` dropdown
- Constructs GitHub raw content URL for logo
- Updates logo `src`, `style`, and `className` properties
- Shows logo when client is selected, hides when no client is selected
- Applies client-specific CSS classes for conditional styling

#### `dashboard/assets/custom_layout.css`
- Added CSS rules for client logo styling
- ENEX: transparent background (displays on dark header)
- Other clients: white background box with rounded corners
- Hides broken images to prevent broken icon display

#### `dashboard/assets/client_logo_handler.js`
- JavaScript error handler for image loading failures
- Automatically hides logo if file doesn't exist or fails to load
- Uses MutationObserver to handle dynamically loaded content

## Testing Steps

### 1. Add Logo Files to Repository

**Important:** Logos must be committed to the Git repository to be accessible via GitHub URLs.

```bash
# Add logo files
git add dashboard/logos/enex.png
git add dashboard/logos/cda.png
git add dashboard/logos/emin.png

# Commit
git commit -m "Add client logos"

# Push to dev branch
git push origin dev
├── cda.png (or cda.jpeg)
└── emin.png (or emin.jpeg)
```

**Logo Specifications:**
- Format: PNG or JPEG
- Height: 48-64px recommended
- Width: Auto-scaled to maintain aspect ratio (max 120px)
- Background styling:
  - **ENEX**: No background box (transparent, displays on dark header)
  - **Other clients**: White background box with rounded corners and shadow
- Color: White/light logos work for ENEX; any color works for other clients with white background

### 2. Start the Application

```bash
python dashboard/app.py
```

### 3. Test Scenarios

#### Scenario 1: Client with Logo
1. Login to the application
2. Select a client that has a logo file (e.g., ENEX)
3. **Expected**: Logo appears next to CODDI logo in header
4. **Verify**: Logo maintains aspect ratio and fits within header height

#### Scenario 2: Client without Logo
1. Select a client that doesn't have a logo file
2. **Expected**: No broken image icon appears
3. **Expected**: Header layout remains intact
4. **Expected**: Only CODDI logo is visible

#### Scenario 3: Client Switching
1. Switch between clients with and without logos
2. **Expected**: Logo updates dynamically without page reload
3. **Expected**: Smooth transition when logo appears/disappears

#### Scenario 4: Multiple Clients
1. Test with all available clients in the system
2. **Expected**: Each client's logo loads correctly
3. **Expected**: Missing logos handled gracefully

### 4. Visual Verification

Check the following visual aspects:

- [ ] Client logo appears next to CODDI logo (not next to title)
- [ ] Logo is vertically centered in header
- [ ] Logo maintains proper spacing (12px margin-left)
- [ ] **ENEX logo**: Displayed directly on dark header (no background box)
- [ ] **Other client logos (CDA, EMIN)**: White background box with rounded corners and shadow
- [ ] White/light-colored logo elements are clearly visible
- [ ] No broken image icon appears for missing logos
- [ ] Header layout remains aligned and responsive

### 5. Console Verification

Open browser developer tools and check console for:

```javascript
// Successful load
"Client logo loaded successfully"

// Failed load (missing file)
"Client logo failed to load, hiding element"
```

Check backend logs for:
```
"Updating client logo for ENEX: https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos/enex.png"
```

### 6. GitHub URL Verification

Verify logos are accessible via GitHub before deployment:

**Test URLs directly in browser:**
```
https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos/enex.png
https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos/cda.png
https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos/emin.png
```

**Expected:** Image files should display in the browser

**If 404 error:** 
- Check file is committed to the repository
- Verify filename matches exactly (case-sensitive)
- Ensure file is pushed to `dev` branch
- Check file path is `dashboard/logos/{filename}.png`

### 7. Network Tab Verification

In browser developer tools (F12) > Network tab:

1. Select a client (e.g., ENEX)
2. Filter by "Img" or "PNG"
3. Look for request to `raw.githubusercontent.com`
4. **Expected:** Status code 200 (success)
5. **If 404:** Logo file not found in repository
6. **If CORS error:** Should not occur with GitHub raw URLs

### 8. Error Handling

Test error conditions:

- [ ] Missing logo file for selected client (should hide gracefully)
- [ ] Invalid client name (should hide logo)
- [ ] Large logo file (verify max-width constraint)
- [ ] Network failure (GitHub temporarily unavailable)
- [ ] Logo not yet pushed to dev branch

**Expected behavior for all errors:**
- No broken image icon appears
- Header layout remains intact
- Console shows appropriate error message
- Logo element is hidden automatically

## Troubleshooting

## Troubleshooting

### Logo Not Appearing

1. **Verify file in repository**: 
   ```bash
   git ls-files dashboard/logos/
   ```
   Should show the logo file

2. **Check file is committed and pushed**:
   ```bash
   git status
   git log --oneline dashboard/logos/
   ```

3. **Test GitHub URL directly**: Open in browser
   ```
   https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos/{client}.png
   ```
   Should display the image

4. **Check filename format**: Must match `{client_lowercase}.png` exactly

5. **Check console**: Look for network errors or JavaScript errors

6. **Check backend logs**: Should see:
   ```
   "Updating client logo for {CLIENT}: https://raw.githubusercontent.com/..."
   ```

### Broken Image Icon Appears

1. **Clear browser cache**: Force reload with Ctrl+F5
2. **Check JavaScript loaded**: Verify `client_logo_handler.js` in Network tab
3. **Check CSS loaded**: Verify `custom_layout.css` is applied
4. **Check element ID**: Verify `client-logo-img` ID exists in DOM
5. **Check Network tab**: Look for 404 errors from githubusercontent.com

### GitHub 404 Error

If logo returns 404 from GitHub:

1. **File not committed**:
   ```bash
   git add dashboard/logos/{client}.png
   git commit -m "Add {client} logo"
   ```

2. **Not pushed to dev branch**:
   ```bash
   git push origin dev
   ```

3. **Wait for GitHub CDN**: Can take 1-2 minutes after push

4. **Check branch name**: Callback uses `dev` branch
   - If using different branch, update callback URL

### Layout Issues

1. **Check CSS**: Verify `custom_layout.css` is loaded
2. **Check spacing**: Verify marginLeft is set correctly
3. **Check container**: Verify logo is in correct flex container
4. **Responsive check**: Test at different screen widths
5. **Check client-specific classes**: Inspect element to verify `client-logo-{client}` class is applied

## Important Notes for Production

### Logo Deployment Workflow

1. Add logo file to `dashboard/logos/`
2. Commit to Git: `git add dashboard/logos/*.png && git commit -m "Add logos"`
3. Push to dev branch: `git push origin dev`
4. Wait 1-2 minutes for GitHub CDN
5. Restart application (optional, logos load from GitHub)
6. Test in browser

### No Server-Side Changes Needed

✅ **Advantage**: Logos load from GitHub, no Flask route required  
✅ **Advantage**: Works in all environments (dev, staging, production)  
✅ **Advantage**: No file system permissions issues  
❗ **Requirement**: Logos must be committed to Git repository  
❗ **Requirement**: GitHub repository must be accessible from deployment environment

## Rollback Instructions

If issues arise, revert the following files to previous versions:

1. `dashboard/layout.py` (remove client logo img element)
2. `dashboard/callbacks/navigation_callbacks.py` (revert logo callback to previous version)
3. `dashboard/assets/custom_layout.css` (remove client logo section)
5. `dashboard/assets/client_logo_handler.js` (delete file)

## Next Steps

1. **Add logo files**: Obtain and add actual client logo files
2. **Optimize images**: Compress PNG files for faster loading
3. **Document requirements**: Update client onboarding documentation
4. **Monitor logs**: Check for any errors in production

## Acceptance Criteria Checklist

- [x] Client logo loads dynamically based on selected client
- [x] Logos stored in `dashboard/logos/` directory
- [x] Filename matches `{client_lowercase}.png` format
- [x] Logo displayed next to CODDI logo (not next to title)
- [x] Logo preserves aspect ratio
- [x] Logo doesn't alter other header elements
- [x] Logo updates when client changes
- [x] Missing logo handled gracefully (no broken icon)
- [x] Case-insensitive client matching (converts to lowercase)
