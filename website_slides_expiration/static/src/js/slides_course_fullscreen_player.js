/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";

// Wait for the widget to be registered, then patch it
const FullscreenPlayerWidget = publicWidget.registry.websiteSlidesFullscreenPlayer;

if (FullscreenPlayerWidget) {
    patch(FullscreenPlayerWidget.prototype, {
        async start() {
            // Extract channel data to get channel ID
            const channelData = this._extractChannelData();
            const channelId = channelData.channelId || channelData.channel_id;

            console.log("Channel ID:", channelId);

            if (!channelId) {
                // No channel ID, proceed normally
                return super.start(...arguments);
            }

            // Check access before creating fullscreen
            try {
                const result = await rpc('/slides/channel/check_access', {
                    channel_id: channelId
                });

                console.log("Access result:", result);

                if (!result.accessible) {
                    // Get the course URL
                    const courseUrl = await this._getCourseUrl(channelId);
                    // Block access - show error
                    console.log("Showing access denied", result);
                    this._showAccessDenied(result.message, result.status, courseUrl);
                    // Return empty promise to prevent fullscreen from loading
                    return Promise.resolve();
                } else {
                    // Access granted - proceed normally
                    return super.start(...arguments);
                }
            } catch (error) {
                console.error('Error checking course access:', error);
                // On error, allow access (fail open)
                return super.start(...arguments);
            }
        },

        async _getCourseUrl(channelId) {
            try {
                const result = await rpc('/web/dataset/call_kw/slide.channel/read', {
                    model: 'slide.channel',
                    method: 'read',
                    args: [[channelId], ['website_url']],
                    kwargs: {}
                });
                return result && result[0] && result[0].website_url ? result[0].website_url : '/slides';
            } catch (error) {
                console.error('Error getting course URL:', error);
                return '/slides';
            }
        },

        _showAccessDenied(message, status, courseUrl) {
            const iconClass = status === 'not_started' ? 'fa-clock-o' : 'fa-lock';
            const title = status === 'not_started' ? 'Course Not Yet Available' : 'Course Has Ended';

            // Find the main element
            const mainElement = this.el || document.querySelector('.o_wslides_fs_main');

            if (!mainElement) {
                console.error("Could not find main element");
                return;
            }

            // Create error HTML
            const errorHTML = `
                <div class="o_wslides_access_denied" style="display: flex; align-items: center; justify-content: center; height: 100vh; width: 100%; background: #1a1a1a; color: white; text-align: center;">
                    <div style="padding: 40px;">
                        <i class="fa ${iconClass} fa-5x" style="color: #dc3545; margin-bottom: 30px;"></i>
                        <h2 style="margin-bottom: 20px;">${title}</h2>
                        <p style="margin: 20px 0; font-size: 18px; opacity: 0.8;">${message}</p>
                        <a href="${courseUrl}" class="btn btn-primary btn-lg" style="margin-top: 20px;">Back to Course Overview</a>
                    </div>
                </div>
            `;

            // Replace the content
            mainElement.innerHTML = errorHTML;

            // Hide footer
            const footer = document.querySelector('.o_footer');
            if (footer) {
                footer.classList.add('d-none');
            }

            console.log("Access denied message displayed");
        }
    });
}