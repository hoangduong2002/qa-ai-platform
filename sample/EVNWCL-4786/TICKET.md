# [EVNWCL-4786] [Image - Documents][Webviewer] Allow users to rotate 2D images directly within the viewer

## Metadata
- Type: Improvement - An improvement or enhancement to an existing feature or task.
- Status: Resolved
- Priority: Major - Major loss of function.
- Assignee: Kent
- Reporter: Wonbin Lim
- Components: Image - Documents, (1), Webviewer
- Resolved: 2026/06/04
- URL: https://vts.vatech.com/browse/EVNWCL-4786

## Description
Item | Contents
--- | ---
Background | In the current imaging viewer, 2D images (e.g. X-ray, panoramic, lateral views) are displayed only in their original orientation. Some images are imported with an incorrect orientation, which impacts readability and user comfort. Currently, users have no way to correct the orientation directly from the viewer.
Purpose | Allow users to rotate 2D images directly within the viewer in order to improve image readability and usability, without requiring external tools
Process(including request items) | Allow users to rotate 2D images directly within the viewer in order to improve image readability and usability, without requiring external tools. Process (including request items) Rotation action Add a rotation button in the 2D image viewer toolbar. Each click rotates the image +90° clockwise. Rotation cycles continuously (0° → 90° → 180° → 270° → 0°). Persistence The selected rotation must be saved: Persisted at image level (database or metadata). Applied automatically when reopening the image. Preserved across sessions and devices. Thumbnail synchronization The rotation must also be applied to: The image thumbnail in the library/list view. Any preview or reduced version of the image. Scope Applies only to 2D images (no impact on CBCT / 3D viewers). No re-encoding of the original image file unless technically required. Rotation should be visually lossless. Attached the functional requirement and MMI MMI : here is the Figma link: UX/UI Improvements
Considerable factors | Rotation state should not impact medical data integrity. Performance: rotation should be instantaneous and not trigger full reloads. UX: Button icon should be explicit (rotate clockwise). Optional tooltip: “Rotate image (90°)”. Technical approach: CSS transform vs. backend-stored rotation flag (to be validated). Ensure consistent behavior between viewer and thumbnails
Resulting Image | User can rotate any 2D image with a single click. Orientation is immediately corrected in the viewer. The rotated orientation remains applied everywhere (viewer + thumbnail) and after reload.

※ If there is no content in each item, use "N/A"

## Custom Fields
- **Delete this attachmentCapture+d%E2%80%99e%CC%81cran+2026-02-10+a%CC%80+15.40.55.png**: 84 kB
- **Delete this attachmentmsedge_0wdRm11G6t.gif**: 32.59 MB
- **trigger**: comment-preview_link
- **fieldId**: comment-preview_link
- **fieldName**: comment-preview_link
- **rendererType**: comment-preview_link
- **issueKey**: comment-preview_link
- **Assignee:**: Kent
- **Manager:**: Kent
- **Discussant:**: Kent
- **Facilitator:**: Kent
- **Votes:**: Kent
- **Watchers:**: Kent
- **Due:**: 2026/06/04
- **Created:**: 2026/06/04
- **Updated:**: 2026/06/04
- **Estimated:**: Kent
- **Remaining:**: Kent
- **Logged:**: Kent
- **Σ Estimated:**: Σ Remaining: 0m
- **Σ Remaining:**: Σ Logged: 1d
- **Σ Logged:**: 1d

## Comments
_No comments_

## Attachments
- [Capture+d%E2%80%99e%CC%81cran+2026-02-10+a%CC%80+15.40.55.png - Latest 2026-02-10 03-43 PM - Kenza GHANDRI](Capture+d%E2%80%99e%CC%81cran+2026-02-10+a%CC%80+15.40.55.png - Latest 2026-02-10 03-43 PM - Kenza GHANDRI)
- [msedge_0wdRm11G6t.gif - Latest 2026-06-04 09-24 AM - Ceuli](msedge_0wdRm11G6t.gif - Latest 2026-06-04 09-24 AM - Ceuli)
