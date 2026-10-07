# SignPath code signing

The release workflow signs Windows EXE and Android APK artifacts using SignPath. macOS disk images are signed on a Mac after CI, with `scripts/sign_and_notarize_macos.sh`, because notarization needs an Apple Developer ID and an interactive notarytool login.

Windows and Android use [SignPath GitHub Actions](https://docs.signpath.io/trusted-build-systems/github) cloud signing (`authenticode-sign` for the portable EXE, `apk-sign` for the APK).

Thank you [SignPath.io](https://signpath.io) for the OSS sponsorships.
