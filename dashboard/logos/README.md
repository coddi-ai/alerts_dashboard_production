# Client Logos

This directory contains client-specific logos displayed in the application header.

## File Naming Convention

Logo filenames must match the client identifier in lowercase:

```
{client_name_lowercase}.png
or
{client_name_lowercase}.jpeg
```

## Examples

- `enex.png` or `enex.jpeg` - ENEX client logo
- `cda.png` or `cda.jpeg` - CDA client logo  
- `emin.png` or `emin.jpeg` - EMIN client logo

## Specifications

- **Format**: PNG or JPEG
- **Recommended height**: 48-64px (logos are scaled to fit header)
- **Aspect ratio**: Preserved automatically
- **Background styling**: 
  - **ENEX**: Displayed directly on dark header (#1a252f) with no background box
  - **Other clients (CDA, EMIN, etc.)**: White background box with rounded corners and shadow
- **Color**: White or light-colored logos work well for ENEX; other clients can use any color

## Usage

Logos are loaded dynamically based on the active client selection. When a client is selected, the dashboard attempts to load the corresponding logo file. If no logo exists, the header continues to display normally without the client logo.
