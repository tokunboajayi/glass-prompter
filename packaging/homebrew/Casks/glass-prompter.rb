cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "2.6.0"
  sha256 arm:   "f65166b46f687975f3e38e377640e86e08cfceb89ab5c37c5ea0f30d3512bcfa",
         intel: "39290e441f1c930a232aea4d7511fa1d0dc3b644667baf4ec18bc5e6d727c9b4"

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
