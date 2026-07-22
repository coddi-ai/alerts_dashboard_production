/**
 * Client Logo Error Handler
 * 
 * Automatically hides the client logo if the image fails to load.
 * This prevents broken image icons from appearing in the header.
 */

// Wait for DOM to be ready
document.addEventListener('DOMContentLoaded', function() {
    
    /**
     * Setup error handler for client logo image
     */
    function setupLogoErrorHandler() {
        const logoImg = document.getElementById('client-logo-img');
        
        if (logoImg) {
            // Add error event listener to hide logo if it fails to load
            logoImg.addEventListener('error', function() {
                console.warn('Client logo failed to load, hiding element');
                this.style.display = 'none';
            });
            
            // Add load event listener to show logo when it loads successfully
            logoImg.addEventListener('load', function() {
                // Only show if src is not empty
                if (this.src && this.src !== window.location.href && this.src !== '') {
                    console.log('Client logo loaded successfully');
                    // Style will be set by callback, but ensure display is not none if callback set it
                    if (this.style.display === 'none' && this.src.includes('/logos/')) {
                        this.style.display = 'block';
                    }
                }
            });
        }
    }
    
    // Setup handler immediately
    setupLogoErrorHandler();
    
    // Also setup after a short delay to handle dynamic content
    setTimeout(setupLogoErrorHandler, 500);
    
    // Use MutationObserver to detect when logo is added to DOM dynamically
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes.length) {
                setupLogoErrorHandler();
            }
        });
    });
    
    // Observe the header area for changes
    const headerArea = document.querySelector('body');
    if (headerArea) {
        observer.observe(headerArea, {
            childList: true,
            subtree: true
        });
    }
});
