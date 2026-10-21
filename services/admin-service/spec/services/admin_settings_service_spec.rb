require 'rails_helper'

RSpec.describe AdminSettingsService do
  let(:redis) { instance_double(Redis, get: nil, set: 'OK', close: nil) }

  before { allow(Redis).to receive(:new).and_return(redis) }

  describe '.auto_investigate_enabled?' do
    it 'defaults to true when the key is unset' do
      expect(described_class.auto_investigate_enabled?).to be(true)
    end

    it 'returns true when the stored value is "true"' do
      allow(redis).to receive(:get).with(described_class::AUTO_INVESTIGATE_KEY).and_return('true')
      expect(described_class.auto_investigate_enabled?).to be(true)
    end

    it 'returns false when the stored value is "false"' do
      allow(redis).to receive(:get).with(described_class::AUTO_INVESTIGATE_KEY).and_return('false')
      expect(described_class.auto_investigate_enabled?).to be(false)
    end

    it 'fails open to true when Redis errors' do
      allow(redis).to receive(:get).and_raise(Redis::CannotConnectError)
      expect(described_class.auto_investigate_enabled?).to be(true)
    end

    it 'closes the connection' do
      described_class.auto_investigate_enabled?
      expect(redis).to have_received(:close)
    end

    it 'connects with REDIS_URL and a 2s timeout' do
      stub_const('ENV', ENV.to_h.merge('REDIS_URL' => 'redis://example:6380/1'))
      described_class.auto_investigate_enabled?
      expect(Redis).to have_received(:new).with(url: 'redis://example:6380/1', timeout: 2)
    end

    it 'builds the URL from REDIS_HOST and REDIS_PORT when REDIS_URL is unset' do
      env = ENV.to_h.except('REDIS_URL').merge('REDIS_HOST' => 'cache', 'REDIS_PORT' => '7000')
      stub_const('ENV', env)
      described_class.auto_investigate_enabled?
      expect(Redis).to have_received(:new).with(url: 'redis://cache:7000/0', timeout: 2)
    end
  end

  describe '.set_auto_investigate' do
    it 'stores the stringified value and closes the connection' do
      described_class.set_auto_investigate(false)
      expect(redis).to have_received(:set).with(described_class::AUTO_INVESTIGATE_KEY, 'false')
      expect(redis).to have_received(:close)
    end

    it 're-raises Redis errors' do
      allow(redis).to receive(:set).and_raise(Redis::CannotConnectError)
      expect { described_class.set_auto_investigate(true) }.to raise_error(Redis::CannotConnectError)
    end
  end
end
