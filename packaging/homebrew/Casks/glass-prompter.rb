cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "2.5.0"
  sha256 arm:   "4cb3a7daf34ee61c6034a611a517da076910319e46e411f69c9073ec4aed9606",
         intel: "4784e438b861b33eff69e4d300d4df82abfee57d31851b4d9e5cd7de52a7dad1"

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
