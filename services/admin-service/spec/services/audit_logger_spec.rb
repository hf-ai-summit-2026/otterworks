require 'rails_helper'

RSpec.describe AuditLogger do
  describe '.log' do
    let(:request) do
      ActionDispatch::TestRequest.create(
        'REMOTE_ADDR' => '10.0.0.7',
        'HTTP_USER_AGENT' => 'RSpec Agent'
      )
    end

    let(:actor_id) { SecureRandom.uuid }
    let(:jwt_user_id) { SecureRandom.uuid }
    let(:resource_id) { SecureRandom.uuid }

    it 'records an audit log with explicit attributes' do
      expect do
        described_class.log(
          action: 'config.updated',
          resource_type: 'SystemConfig',
          resource_id: resource_id,
          actor_id: actor_id,
          actor_email: 'actor@otterworks.com',
          changes_made: { 'value' => 'new' }
        )
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(
        action: 'config.updated',
        resource_type: 'SystemConfig',
        resource_id: resource_id,
        actor_id: actor_id,
        actor_email: 'actor@otterworks.com',
        changes_made: { 'value' => 'new' },
        ip_address: nil,
        user_agent: nil
      )
    end

    it 'derives actor and client details from the request' do
      set_jwt_env(request, user_id: jwt_user_id, email: 'jwt@otterworks.com')

      described_class.log(action: 'user.updated', resource_type: 'AdminUser', request: request)

      expect(AuditLog.last).to have_attributes(
        actor_id: jwt_user_id,
        actor_email: 'jwt@otterworks.com',
        ip_address: '10.0.0.7',
        user_agent: 'RSpec Agent'
      )
    end

    it 'prefers explicit actor over request JWT claims' do
      set_jwt_env(request, user_id: jwt_user_id, email: 'jwt@otterworks.com')

      described_class.log(action: 'user.updated', resource_type: 'AdminUser', request: request,
                          actor_id: actor_id, actor_email: 'explicit@otterworks.com')

      expect(AuditLog.last).to have_attributes(actor_id: actor_id, actor_email: 'explicit@otterworks.com')
    end

    it 'swallows and logs errors instead of raising' do
      allow(Rails.logger).to receive(:error)

      expect do
        described_class.log(action: nil, resource_type: 'AdminUser')
      end.not_to raise_error

      expect(AuditLog.count).to eq(0)
      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
