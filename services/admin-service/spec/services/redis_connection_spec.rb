require 'rails_helper'

RSpec.describe RedisConnection do
  describe '.url' do
    it 'uses REDIS_URL when set' do
      with_env('REDIS_URL' => 'redis://cache:6380/2', 'REDIS_HOST' => 'ignored') do
        expect(described_class.url).to eq('redis://cache:6380/2')
      end
    end

    it 'builds the URL from REDIS_HOST and REDIS_PORT' do
      with_env('REDIS_URL' => nil, 'REDIS_HOST' => 'redis', 'REDIS_PORT' => '6390') do
        expect(described_class.url).to eq('redis://redis:6390/0')
      end
    end

    it 'defaults to localhost:6379' do
      with_env('REDIS_URL' => nil, 'REDIS_HOST' => nil, 'REDIS_PORT' => nil) do
        expect(described_class.url).to eq('redis://localhost:6379/0')
      end
    end
  end

  describe '.build' do
    it 'creates a client with the resolved URL and a 2s timeout' do
      allow(Redis).to receive(:new).and_return(:client)
      with_env('REDIS_URL' => 'redis://cache:6379/0') do
        expect(described_class.build).to eq(:client)
      end
      expect(Redis).to have_received(:new).with(url: 'redis://cache:6379/0', timeout: 2)
    end
  end
end
