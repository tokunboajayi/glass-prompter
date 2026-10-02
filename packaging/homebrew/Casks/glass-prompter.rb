cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "2.4.0"
  sha256 arm:   "7a7373e28cca06d59a5c4396df8389ff88947ce6208415ef71e0a56dfbecbfbd",
         intel: "c6323d5785cf88b8a37df8c975ac14682008f526d9e152bc8d04a2b54e5dcc2b"

  url "https://github.com/tokunboajayi/glass-prompter/releases/download/v#{version}/GlassPrompter-#{version}-macOS-#{arch}.dmg"
  name "Glass Prompter"
  desc "See-through teleprompter under your webcam that follows your voice"
  homepage "https://tokunboajayi.github.io/glass-prompter/"

  livecheck do
    url :url
    strategy :github_latest
  end

  auto_updates true
  depends_on macos: ">= :ventura"

  app "Glass Prompter.app"

  zap trash: [
    "~/Library/Application Support/GlassPrompter",
    "~/Library/LaunchAgents/app.glassprompter.plist",
  ]

  caveats <<~EOS
    Glass Prompter is not notarized yet. The first time, right-click it in Applications and choose Open
    (on macOS 15+: System Settings > Privacy & Security > Open Anyway).
  EOS
end
