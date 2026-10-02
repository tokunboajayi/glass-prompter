cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "2.3.0"
  sha256 arm:   "7efa07844e2c39b1b6e9ca51cf0610392b7b914384cfe52eecc154127f0be6be",
         intel: "9dfbbd1a90dc0e439b1fcd711d6b14ec164a5b1cd25d5564d4b8175dd3f99b19"

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
