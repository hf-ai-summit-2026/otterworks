require 'rails_helper'

RSpec.describe AdminSettingsService do
  let(:redis) { instance_double(Redis, get: nil, set: 'OK', close: nil) }

  before { allow(RedisConnection).to receive(:build).and_return(redis) }

  describe '.auto_investigate_enabled?' do
    it 'defaults to true when the key is unset' do
      expect(described_class.auto_investigate_enabled?).to be(true)
      expect(redis).to have_received(:close)
    end

    it 'returns true when stored as "true"' do
      allow(redis).to receive(:get).with('admin:auto_investigate').and_return('true')
      expect(described_class.auto_investigate_enabled?).to be(true)
    end

    it 'returns false when stored as "false"' do
      allow(redis).to receive(:get).and_return('false')
      expect(described_class.auto_investigate_enabled?).to be(false)
    end

    it 'fails open when Redis is unavailable' do
      allow(redis).to receive(:get).and_raise(Redis::CannotConnectError)
      expect(described_class.auto_investigate_enabled?).to be(true)
      expect(redis).to have_received(:close)
    end
  end

  describe '.set_auto_investigate' do
    it 'stores the flag as a string and closes the connection' do
      described_class.set_auto_investigate(false)
      expect(redis).to have_received(:set).with('admin:auto_investigate', 'false')
      expect(redis).to have_received(:close)
    end

    it 're-raises Redis errors' do
      allow(redis).to receive(:set).and_raise(Redis::CannotConnectError)
      expect { described_class.set_auto_investigate(true) }.to raise_error(Redis::CannotConnectError)
      expect(redis).to have_received(:close)
    end
  end
end
