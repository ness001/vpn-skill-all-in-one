Clash Verge Rev v2.5.2 — upstream licenses and source access
Verified 2026-09-19.

The public repository contains official release/source links and notices only;
installers, runtime packages and source archive bytes are not included.

Read these notices with the installers:
- LICENSE.gui.txt: exact GUI release license, GPL version 3.
  Tagged Cargo.toml declares GPL-3.0-only.
- LICENSE.mihomo.txt: exact license of BOTH bundled Mihomo cores, GPL version 3.
- LICENSE.service.txt: exact bundled service v2.3.3 license, GPL version 3.
- NOTICE.txt: version/build evidence, source-access obligations and limitations.
- NOTICE.WebView2.txt: separate Microsoft terms and required privacy notice.
- LICENSE.WebView2.txt: full current Microsoft Evergreen runtime terms offline.
- LICENSE.WebView2.html.txt: verbatim official HTML license value, as text.
- sources.json: pinned source commits, download links and license-file hashes.

Windows offline installation uses the regular Clash Verge installer plus the
separate Microsoft-direct Evergreen Standalone x64 runtime 153.0.4234.48. If
WebView2 is missing, read its license and privacy notice, download from Microsoft and install the
runtime FIRST, then install Clash Verge. The companion link is supplied only for this
application, not as an independent runtime offering. Nothing here accepts terms
for the recipient or claims that the recipient already agreed. An existing
sufficiently current WebView2 installation can be reused. No Microsoft
endorsement or GPL license for Microsoft's runtime is implied.

Pinned GUI, both Mihomo cores and service source archive URLs remain in
../../sources/manifest.json and sources.json. Source archives are not mirrored
locally. Their recorded hashes describe previously checked archives; no new
network verification is implied. Installing an app does not require its source.

Keep these files and upstream notices with any redistribution. Anyone
redistributing the packages remains responsible for maintaining equivalent
access to the complete corresponding source for as long as required by GPLv3,
including build scripts and applicable dependencies. A link list alone is not
a certification of complete corresponding-source coverage. The upstream GUI,
core and service archives are source entry points, not an independently
verified, fully vendored or offline-reproducible dependency bundle.

No licenses of unrelated components are replaced by the GUI's GPL declaration.
The Microsoft WebView2 runtime is NOT relicensed under GPL. Preserve all
third-party notices already present inside the unchanged upstream installers.
