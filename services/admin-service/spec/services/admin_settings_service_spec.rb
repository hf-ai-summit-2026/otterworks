require 'rails_helper'

RSpec.describe AdminSettingsService do
  let(:redis) { instance_double(Redis, get: nil, set: 'OK', close: nil) }

  before { allow(Redis).to receive(:new).and_return(redis) }

  describe '.auto_investigate_enabled?' do
    it 'defaults to true when the key is unset' do
      expect(described_class.auto_investigate_enabled?).to be true
    end

    it "returns true when the stored value is 'true'" do
      allow(redis).to receive(:get).with(described_class::AUTO_INVESTIGATE_KEY).and_return('true')
      expect(described_class.auto_investigate_enabled?).to be true
    end

    it "returns false when the stored value is 'false'" do
      allow(redis).to receive(:get).with(described_class::AUTO_INVESTIGATE_KEY).and_return('false')
      expect(described_class.auto_investigate_enabled?).to be false
    end

    it 'fails open when Redis is unavailable' do
      allow(redis).to receive(:get).and_raise(Redis::CannotConnectError)
      expect(described_class.auto_investigate_enabled?).to be true
    end

    it 'closes the connection' do
      described_class.auto_investigate_enabled?
      expect(redis).to have_received(:close)
    end
  end

  describe '.set_auto_investigate' do
    it 'stores the flag as a string' do
      described_class.set_auto_investigate(false)
      expect(redis).to have_received(:set).with(described_class::AUTO_INVESTIGATE_KEY, 'false')
    end

    it 're-raises Redis errors and still closes the connection' do
      allow(redis).to receive(:set).and_raise(Redis::CannotConnectError)
      expect { described_class.set_auto_investigate(true) }.to raise_error(Redis::CannotConnectError)
      expect(redis).to have_received(:close)
    end
  end
end
