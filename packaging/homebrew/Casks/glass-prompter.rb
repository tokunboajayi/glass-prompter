cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "2.2.0"
  sha256 arm:   "07c7ddd2c370d34324550c5289ffc57e2ee3a194de130eab95f9a815190d6417",
         intel: "0215ccd4bfac74e57bcb80e6984fb9cd06b74edcc6cc1c5fa7be22bfd7bec2fd"

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
