require 'rails_helper'

RSpec.describe AuditLogger do
  describe '.log' do
    let(:jwt_user_id) { SecureRandom.uuid }
    let(:actor_id) { SecureRandom.uuid }
    let(:resource_id) { SecureRandom.uuid }
    let(:request) do
      instance_double(
        ActionDispatch::Request,
        env: { 'jwt.user_id' => jwt_user_id, 'jwt.user_email' => 'jwt@otterworks.dev' },
        remote_ip: '10.0.0.5',
        user_agent: 'RSpec/1.0'
      )
    end

    it 'records an audit log with the given attributes' do
      expect do
        described_class.log(action: 'config.updated', resource_type: 'SystemConfig', resource_id: resource_id,
                            actor_id: actor_id, actor_email: 'actor@otterworks.dev',
                            changes_made: { 'value' => %w[old new] })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(
        action: 'config.updated', resource_type: 'SystemConfig', resource_id: resource_id,
        actor_id: actor_id, actor_email: 'actor@otterworks.dev',
        changes_made: { 'value' => %w[old new] }, ip_address: nil, user_agent: nil
      )
    end

    it 'falls back to the JWT actor and request metadata when no actor is given' do
      described_class.log(action: 'quota.updated', resource_type: 'StorageQuota', request: request)

      expect(AuditLog.last).to have_attributes(
        actor_id: jwt_user_id, actor_email: 'jwt@otterworks.dev',
        ip_address: '10.0.0.5', user_agent: 'RSpec/1.0'
      )
    end

    it 'prefers an explicit actor over the JWT actor' do
      described_class.log(action: 'quota.updated', resource_type: 'StorageQuota', request: request,
                          actor_id: actor_id, actor_email: 'explicit@otterworks.dev')

      expect(AuditLog.last).to have_attributes(actor_id: actor_id, actor_email: 'explicit@otterworks.dev')
    end

    it 'logs and swallows errors instead of raising' do
      allow(Rails.logger).to receive(:error)

      expect do
        expect(described_class.log(action: nil, resource_type: 'StorageQuota')).to be_nil
      end.not_to change(AuditLog, :count)

      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
