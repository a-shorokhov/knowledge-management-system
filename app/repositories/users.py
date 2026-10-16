users = {}


class UserRepository:
    def create_user(self, username: str, email: str, password: str):
        # после удаления айди может повториться, заменить при подключении бд
        user_id = len(users) + 1

        users[user_id] = {
            "id": user_id,
            "username": username,
            "email": email,
            "password": password,
        }

        return users[user_id]

    def get_all_users(self):
        return users

    def get_user_by_id(self, user_id: int):
        return users.get(user_id)

    def get_user_by_username(self, username: str):
        for user in users.values():
            if user["username"] == username:
                return user

        return None

    def edit_user(self, user_id: int, upd_data: dict):
        users[user_id].update(upd_data)

    def delete_user(self, user_id: int):
        users.pop(user_id)