# Client Logo Implementation - Testing Guide

## Implementation Summary

The client logo feature has been successfully implemented with the following components:

### 1. Directory Structure
- Location: `dashboard/logos/`
- Naming convention: `{client_lowercase}.png`
- Examples:
  - `dashboard/logos/enex.png`
  - `dashboard/logos/cda.png`
  - `dashboard/logos/emin.png`

### 2. Modified Files

#### `dashboard/layout.py`
- Added client logo `<img>` element with ID `client-logo-img` next to CODDI logo
- Positioned in the left branding section of the header
- Set to hidden by default

#### `dashboard/app.py`
- Added Flask route `/logos/<filename>` to serve logo files
- Imported `send_from_directory` from Flask
- Returns 404 for missing logos (handled gracefully by frontend)

#### `dashboard/callbacks/navigation_callbacks.py`
- Added callback to update client logo based on `client-selector` dropdown
- Updates logo `src` and `style` properties
- Shows logo when client is selected, hides when no client is selected

#### `dashboard/assets/custom_layout.css`
- Added CSS rules for client logo styling
- Hides broken images to prevent broken icon display

#### `dashboard/assets/client_logo_handler.js`
- JavaScript error handler for image loading failures
- Automatically hides logo if file doesn't exist or fails to load
- Uses MutationObserver to handle dynamically loaded content

## Testing Steps

### 1. Add Logo Files

Place logo images in `dashboard/logos/` directory:

```bash
# Example structure
dashboard/logos/
├── enex.png (or enex.jpeg)
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

// Backend log
"Serving logo file: enex.png from {path}"
```

### 6. Error Handling

Test error conditions:

- [ ] Invalid filename in URL (direct access to `/logos/invalid.png`)
- [ ] Missing logo file for selected client
- [ ] Corrupted logo file
- [ ] Large logo file (verify max-width constraint)

## Troubleshooting

### Logo Not Appearing

1. **Check file exists**: Verify logo file is in `dashboard/logos/` directory
2. **Check filename**: Must match `{client_lowercase}.png` format
3. **Check permissions**: Ensure file is readable by the application
4. **Check console**: Look for 404 errors or JavaScript errors
5. **Check Flask logs**: Verify route is being called

### Broken Image Icon Appears

1. **Clear browser cache**: Force reload with Ctrl+F5
2. **Check JavaScript loaded**: Verify `client_logo_handler.js` in Network tab
3. **Check CSS loaded**: Verify `custom_layout.css` is applied
4. **Check element ID**: Verify `client-logo-img` ID exists in DOM

### Layout Issues

1. **Check CSS**: Verify `custom_layout.css` is loaded
2. **Check spacing**: Verify marginLeft is set correctly
3. **Check container**: Verify logo is in correct flex container
4. **Responsive check**: Test at different screen widths

## Rollback Instructions

If issues arise, revert the following files to previous versions:

1. `dashboard/layout.py` (remove client logo img element)
2. `dashboard/app.py` (remove `/logos/` route)
3. `dashboard/callbacks/navigation_callbacks.py` (remove logo callback)
4. `dashboard/assets/custom_layout.css` (remove client logo section)
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
